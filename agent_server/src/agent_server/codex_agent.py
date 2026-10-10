"""Codex SDK decision runner over the existing semantic-action contract."""

from __future__ import annotations

import asyncio
import json
import time
import tomllib
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import ContractError, DecisionRequest, translate_intent
from agent_sdk.state import StateDelta
from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox, SkillInput, TextInput

from agent_server.codex_mcp_bridge import CodexMcpBridge
from agent_server.config import ServiceSettings
from agent_server.duel_context import DuelContext
from agent_server.duel_tools import TOOLSET_VERSION, ClientQuery, DecisionDeps, DecisionFailure
from agent_server.model_agent import (
    DecisionOutput,
    intent_format,
)
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase
from agent_server.trace import TraceWriter, safe_value


def decision_output_schema(request: DecisionRequest) -> dict[str, Any]:
    """Build a strict schema for the current prompt's semantic action shapes."""
    item_shapes: dict[str, dict[str, Any]] = {
        "choice": {"candidate_id": {"type": "string"}},
        "select_step": {"candidate_id": {"type": "string"}},
        "select_cards": {"candidate_ids": {"type": "array", "items": {"type": "string"}}},
        "select_places": {
            "places": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "controller": {"type": "integer"},
                        "location": {"type": "string"},
                        "sequence": {"type": "integer"},
                    },
                    "required": ["controller", "location", "sequence"],
                    "additionalProperties": False,
                },
            }
        },
        "distribute_counters": {
            "allocations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                    "required": ["candidate_id", "count"],
                    "additionalProperties": False,
                },
            }
        },
        "announce_card": {"card_id": {"type": "integer"}},
    }
    variants: list[dict[str, Any]] = []
    for fmt in intent_format(request)["formats"]:
        kind = fmt["kind"]
        if kind not in item_shapes:
            raise DecisionFailure("unsupported_prompt", "unknown semantic action shape")
        fields = item_shapes[kind]
        variants.append(
            {
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": [kind]}, **fields},
                "required": ["kind", *fields],
                "additionalProperties": False,
            }
        )
    if not variants:
        raise DecisionFailure("unsupported_prompt", "prompt has no semantic action schema")
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "intent": variants[0] if len(variants) == 1 else {"anyOf": variants},
        },
        "required": ["reason", "intent"],
        "additionalProperties": False,
    }


def codex_settings(home: Path, workspace: Path, bridge: CodexMcpBridge) -> CodexConfig:
    """Force the game sandbox and its only MCP server without rewriting user settings."""
    raw = bridge.mcp_config()
    overrides = [
        'approval_policy="never"',
        'sandbox_mode="read-only"',
        'web_search="disabled"',
        "project_doc_max_bytes=0",
        'project_root_markers=[".ygopro-agent-root"]',
        "features.shell_tool=false",
        "features.unified_exec=false",
        "features.apps=false",
        "features.hooks=false",
        "features.goals=false",
        "agents.enabled=false",
    ]
    for key in ("command", "args"):
        overrides.append(f"mcp_servers.ygopro_duel.{key}={json.dumps(raw[key])}")
    for key, value in raw["env"].items():
        overrides.append(f"mcp_servers.ygopro_duel.env.{key}={json.dumps(value)}")
    # A separate HOME keeps Codex's global skill discovery away from the real user home.
    env = {
        "CODEX_HOME": str(home),
        "HOME": str(home),
        "CODEX_API_KEY": "",
        "CODEX_ACCESS_TOKEN": "",
        "OPENAI_API_KEY": "",
    }
    return CodexConfig(
        cwd=str(workspace),
        env=env,
        config_overrides=tuple(overrides),
        client_name="ygopro_duel_agent",
        client_title="YGOPro Duel Agent",
    )


def _validate_user_config(home: Path) -> dict[str, Any]:
    """Reject config surfaces that could add capabilities beyond the duel MCP."""
    path = home / "config.toml"
    if path.is_symlink():
        raise ValueError("Codex config must not be a symlink")
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        settings = tomllib.load(stream)
    allowed = {"model", "model_reasoning_effort", "model_reasoning_summary"}
    disallowed = set(settings) - allowed
    if disallowed:
        raise ValueError(
            "Codex config contains unsupported runtime keys: " + ", ".join(sorted(disallowed))
        )
    return settings


def _prepare_directories(root: Path, profile_dir: Path) -> tuple[Path, Path]:
    codex = profile_dir / "codex"
    home, workspace = codex / "codex_home", codex / "workspace"
    for path in (profile_dir, codex, home, workspace):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Codex runtime directory must stay inside the release root")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    (workspace / ".ygopro-agent-root").touch(exist_ok=True)
    return home, workspace


class CodexDecisionAgent:
    """One service child owns one Codex app-server and persistent duel threads."""

    def __init__(
        self,
        settings: ServiceSettings,
        store: StateDatabase,
        skills: SkillResources,
        profile_dir: Path,
        *,
        codex_factory: Any = AsyncCodex,
    ) -> None:
        self.settings = settings
        self.store = store
        self.skills = skills
        self.context = DuelContext(skills.root, store, skills)
        self.home, self.workspace = _prepare_directories(skills.root, profile_dir)
        self.user_config = _validate_user_config(self.home)
        self.bridge = CodexMcpBridge()
        self.codex_factory = codex_factory
        self.codex: Any = None
        self.threads: dict[tuple[str, str], Any] = {}
        self._usage_ratio: dict[tuple[str, str], float] = {}
        self._decision_lock = asyncio.Lock()

    async def start(self) -> None:
        await self.bridge.start()
        try:
            self.codex = self.codex_factory(codex_settings(self.home, self.workspace, self.bridge))
            await self.codex.__aenter__()
            account = await self.codex.account(refresh_token=True)
            if account.account is None or account.account.root.type != "chatgpt":
                raise DecisionFailure(
                    "provider_unavailable", "Codex ChatGPT login required; run --init-codex"
                )
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self.codex is not None:
            await self.codex.close()
            self.codex = None
        await self.bridge.close()

    async def finish_duel(self, session: str, duel: str) -> None:
        """Archive the native thread after the authority reports a terminal duel."""
        async with self._decision_lock:
            key = (session, duel)
            record = self.store.get_latest_record(session, duel, "codex_thread")
            if record is None or self.codex is None:
                return
            thread_id = cast(dict[str, Any], record["payload"]).get("thread_id")
            if not isinstance(thread_id, str):
                return
            self.threads.pop(key, None)
            self._usage_ratio.pop(key, None)
            try:
                await self.codex.thread_archive(thread_id)
            except Exception as exc:
                self.store.add_trace(
                    session,
                    duel,
                    "",
                    None,
                    "codex_archive_failed",
                    {"error": type(exc).__name__},
                )
            else:
                self.store.add_trace(
                    session, duel, "", None, "codex_thread_archived", {"thread_id": thread_id}
                )

    async def _thread(self, session: str, duel: str, prompt_text: str) -> tuple[Any, bool]:
        key = (session, duel)
        if key in self.threads:
            return self.threads[key], False
        if self.codex is None:
            raise DecisionFailure("provider_unavailable", "Codex has not started")
        record = self.store.get_latest_record(session, duel, "codex_thread")
        if (
            record is not None
            and cast(dict[str, Any], record["payload"]).get("toolset_version") == TOOLSET_VERSION
        ):
            thread_id = cast(dict[str, Any], record["payload"]).get("thread_id")
            if not isinstance(thread_id, str) or not thread_id:
                raise DecisionFailure("storage_error", "Codex thread record is invalid")
            thread = await self.codex.thread_resume(
                thread_id,
                approval_mode=ApprovalMode.deny_all,
                cwd=str(self.workspace),
                sandbox=Sandbox.read_only,
            )
            first = False
        else:
            thread = await self.codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                base_instructions=prompt_text,
                cwd=str(self.workspace),
                sandbox=Sandbox.read_only,
            )
            self.store.append_record(
                session,
                duel,
                "codex_thread",
                f"toolset-v{TOOLSET_VERSION}",
                {"thread_id": thread.id, "toolset_version": TOOLSET_VERSION},
            )
            first = True
        self.threads[key] = thread
        return thread, first

    @staticmethod
    def _event_dict(event: Any) -> dict[str, Any]:
        payload = getattr(event, "payload", None)
        if payload is not None and hasattr(payload, "model_dump"):
            value: object = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        elif isinstance(payload, dict):
            value = cast(dict[str, Any], payload)
        else:
            value = {}
        return cast(dict[str, Any], value) if isinstance(value, dict) else {}

    async def _run_turn(
        self,
        thread: Any,
        prompt: str,
        first: bool,
        trace: TraceWriter,
        key: tuple[str, str],
        output_schema: dict[str, Any],
    ) -> str:
        inputs: list[Any] = [TextInput(text=prompt)]
        if first:
            for name in ("ocg-rulebook", "ygo-card-db"):
                path = self.skills.root / ".agents" / "skills" / name / "SKILL.md"
                inputs.append(SkillInput(name=name, path=str(path)))
        handle = await thread.turn(
            inputs,
            approval_mode=ApprovalMode.deny_all,
            sandbox=Sandbox.read_only,
            output_schema=output_schema,
        )
        final: str | None = None
        fallback: str | None = None
        finished = False
        status = ""
        trace.start_response()
        turn_started = time.perf_counter()
        trace.emit("provider_request_started", {"backend": "codex"})
        usage: dict[str, Any] | None = None
        try:
            async for event in handle.stream():
                method = str(getattr(event, "method", ""))
                payload = self._event_dict(event)
                if method == "item/agentMessage/delta":
                    trace.text("assistant_text", str(payload.get("delta", "")))
                elif method == "item/reasoning/summaryTextDelta":
                    trace.text("provider_reasoning", str(payload.get("delta", "")), form="summary")
                elif method == "item/reasoning/textDelta":
                    trace.text("provider_reasoning", str(payload.get("delta", "")), form="text")
                elif method in ("item/started", "item/completed"):
                    item = payload.get("item")
                    if isinstance(item, dict):
                        item = cast(dict[str, Any], item)
                        trace.emit("codex_item", {"method": method, "item": safe_value(item)})
                        if item.get("type") == "mcpToolCall":
                            trace.emit(
                                "tool_started" if method == "item/started" else "tool_finished",
                                {"tool_name": item.get("tool"), "details": safe_value(item)},
                            )
                        if method == "item/completed" and item.get("type") == "agentMessage":
                            content = item.get("text")
                            if isinstance(content, str):
                                if item.get("phase") == "finalAnswer":
                                    final = content
                                elif item.get("phase") is None:
                                    fallback = content
                elif method == "thread/tokenUsage/updated":
                    trace.emit("codex_usage", payload)
                    usage = payload.get("tokenUsage")
                    if isinstance(usage, dict):
                        last = usage.get("last")
                        window = usage.get("modelContextWindow")
                        if isinstance(last, dict) and type(window) is int and window > 0:
                            tokens = cast(dict[str, Any], last).get("inputTokens")
                            if type(tokens) is int and tokens >= 0:
                                self._usage_ratio[key] = tokens / window
                elif method == "turn/completed":
                    turn = payload.get("turn")
                    if isinstance(turn, dict):
                        turn = cast(dict[str, Any], turn)
                        status = str(turn.get("status", ""))
                        if status == "failed":
                            trace.emit("codex_turn_failed", {"error": turn.get("error")})
                    finished = True
        except asyncio.CancelledError:
            try:
                async with asyncio.timeout(2):
                    await asyncio.shield(handle.interrupt())
            except Exception:
                # A turn that cannot be interrupted must not keep using the
                # persistent MCP connection after the next decision activates.
                if self.codex is not None:
                    await self.codex.close()
                    self.codex = None
            finally:
                raise
        finally:
            raw_last = usage.get("last") if isinstance(usage, dict) else None
            last_usage: dict[str, Any] = (
                cast(dict[str, Any], raw_last) if isinstance(raw_last, dict) else {}
            )
            trace.emit(
                "provider_request_finished",
                {
                    "backend": "codex",
                    "duration_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                    "status": status or "interrupted",
                    "usage": {
                        "input_count": last_usage.get("inputTokens"),
                        "output_count": last_usage.get("outputTokens"),
                        "reasoning_count": last_usage.get("reasoningOutputTokens"),
                    },
                },
            )
            trace.finish_response()
        if not finished or status != "completed":
            raise DecisionFailure("provider_unavailable", "Codex turn failed or was interrupted")
        answer = final or fallback
        if answer is None:
            raise DecisionFailure("invalid_intent", "Codex turn returned no final answer")
        return answer

    async def decide(
        self, request: DecisionRequest, delta: StateDelta, query_client: ClientQuery
    ) -> tuple[dict[str, Any], str]:
        # A persistent MCP connection carries no turn ID. Never let an old turn's
        # late tool call be served against the next decision's active context.
        async with self._decision_lock:
            return await self._decide_locked(request, delta, query_client)

    async def _decide_locked(
        self, request: DecisionRequest, delta: StateDelta, query_client: ClientQuery
    ) -> tuple[dict[str, Any], str]:
        data = request.data
        session, duel = cast(str, data["session_id"]), cast(str, data["duel_id"])
        deadline_ms = cast(int, data["deadline_unix_ms"])
        remaining = (deadline_ms - int(time.time() * 1000)) / 1000
        if remaining <= 0:
            raise DecisionFailure("timeout", "decision deadline expired")
        self.context.ensure(request)
        pinned = self.context.prompt(session, duel)
        thread, created = await self._thread(session, duel, pinned["text"])
        first = created or self.store.get_latest_record(session, duel, "model_exchange") is None
        deps = DecisionDeps(
            request,
            delta,
            self.store,
            self.skills,
            self.settings,
            query_client,
            time.monotonic() + remaining,
            pinned["text"],
        )
        prompt_payload: dict[str, Any] = {
            "state_version": data["state_version"],
            "ack_event_id": delta.ack_event_id,
            "new_events": delta.events,
            "net_changes": delta.changes,
            "prompt": data["prompt"],
            "intent_format": intent_format(request),
            "budget": {
                "host_tool_attempts": self.settings.limits.host_tool_attempts,
                "deadline_unix_ms": deadline_ms,
            },
        }
        if first:
            prompt_payload["initial_state"] = self.store.get_state(
                session, duel, cast(int, data["state_version"])
            )
            prompt_payload["own_deck_catalog"] = self.context.catalog(session, duel)
        prompt = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
        turn_id = f"{data['prompt_id']}:{data['state_version']}"
        trace = TraceWriter(self.store, session, duel, turn_id)
        deps.emit_tool_metric = trace.emit
        trace.emit(
            "model_request_started",
            {
                "backend": "codex",
                "prompt": prompt_payload,
                "reasoning_effort_configured": self.user_config.get("model_reasoning_effort"),
                "reasoning_summary_configured": self.user_config.get("model_reasoning_summary"),
            },
        )
        key = (session, duel)
        ratio = self._usage_ratio.get(key, 0.0)
        if ratio >= self.settings.compaction.trigger_fraction:
            trace.emit("codex_compaction_started", {"input_context_fraction": ratio})
            compact_started = time.perf_counter()
            try:
                timeout = min(
                    self.settings.compaction.summary_timeout_seconds,
                    max(0.1, (deadline_ms - int(time.time() * 1000)) / 3000),
                )
                async with asyncio.timeout(timeout):
                    await thread.compact()
            except Exception as exc:
                trace.emit("codex_compaction_failed", {"error": type(exc).__name__})
            else:
                self._usage_ratio.pop(key, None)
                trace.emit(
                    "codex_compaction_finished",
                    {"duration_ms": round((time.perf_counter() - compact_started) * 1000, 2)},
                )
        self.bridge.activate(deps, self.context)
        started = time.perf_counter()
        try:
            for attempt in range(1, self.settings.limits.invalid_intent_attempts + 1):
                async with asyncio.timeout(max(0, (deadline_ms - int(time.time() * 1000)) / 1000)):
                    answer = await self._run_turn(
                        thread,
                        prompt,
                        first and attempt == 1,
                        trace,
                        key,
                        decision_output_schema(request),
                    )
                try:
                    output = DecisionOutput.model_validate_json(answer)
                    action = translate_intent(request, output.intent)
                except (ValueError, ContractError) as exc:
                    trace.emit(
                        "intent_validation", {"valid": False, "attempt": attempt, "error": str(exc)}
                    )
                    if attempt >= self.settings.limits.invalid_intent_attempts:
                        raise DecisionFailure(
                            "invalid_intent", "Codex exceeded validation retries"
                        ) from exc
                    prompt = (
                        f"上一轮语义动作无效：{exc}。只根据当前合法候选重新输出 reason 和 intent。"
                    )
                    continue
                trace.emit("intent_validation", {"valid": True, "attempt": attempt})
                record_id = turn_id
                self.store.append_record(
                    session,
                    duel,
                    "model_exchange",
                    record_id,
                    {
                        "backend": "codex",
                        "reason": output.reason,
                        "intent": output.intent,
                        "action": action,
                        "tool_attempts": deps.tool_records,
                    },
                )
                trace.emit(
                    "model_decision",
                    {
                        "reason": output.reason,
                        "intent": output.intent,
                        "action": action,
                        "tool_attempts": deps.tool_records,
                    },
                )
                trace.emit(
                    "decision_timing",
                    {
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "status": "completed",
                        "invalid_intent_attempts": attempt - 1,
                        "host_tool_attempts": deps.host_tool_attempts,
                        "client_queries": deps.client_queries,
                    },
                )
                return action, output.reason
            raise DecisionFailure("invalid_intent", "Codex returned no valid intent")
        except TimeoutError as exc:
            raise DecisionFailure("timeout", "decision deadline expired") from exc
        except DecisionFailure:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise DecisionFailure("provider_unavailable", "Codex request failed") from exc
        finally:
            self.bridge.deactivate()
            trace.flush()
