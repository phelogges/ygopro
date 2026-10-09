"""Pydantic AI decision runner and perspective-scoped read-only tools."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from agent_sdk.contract import ContractError, DecisionRequest, translate_intent
from agent_sdk.state import StateDelta, StateError
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelMessagesTypeAdapter, RunContext, ToolOutput, UsageLimits
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelRetry,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai_harness import CodeMode
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    FallbackCompaction,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
)

from agent_server.budget_model import (
    BudgetModel,
    ModelBudget,
    ModelTelemetry,
    current_budget,
    current_telemetry,
)
from agent_server.config import ServiceSettings, model_api_key
from agent_server.duel_context import DuelContext
from agent_server.hand_notes import HandNotes
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase
from agent_server.trace import TraceWriter


def intent_format(request: DecisionRequest) -> dict[str, Any]:
    """Describe the action shapes accepted by the deterministic SDK translator."""
    kind = request.prompt["kind"]
    constraints = request.prompt["constraints"]
    formats: list[dict[str, Any]] = []
    if kind in {
        "idle_command",
        "battle_command",
        "yes_no",
        "effect_yes_no",
        "option",
        "chain",
        "position",
        "announce_number",
        "rock_paper_scissors",
        "first_player",
        "effect_yesno",
        "yesno",
    }:
        formats.append({"kind": "choice", "candidate_id": "<所选候选 id>"})
    if kind in {
        "select_card",
        "select_cards",
        "tribute",
        "sum",
        "sort",
        "announce_race",
        "announce_attribute",
    }:
        formats.append({"kind": "select_cards", "candidate_ids": ["<所选候选 id>"]})
        if any(candidate["kind"] in {"cancel", "default"} for candidate in request.candidates):
            formats.append({"kind": "choice", "candidate_id": "<取消或默认候选 id>"})
    if kind in {"unselect_card", "select_unselect_card"}:
        formats.append({"kind": "select_step", "candidate_id": "<所选候选 id>"})
        if any(candidate["kind"] in {"cancel", "finish"} for candidate in request.candidates):
            formats.append({"kind": "choice", "candidate_id": "<取消或完成候选 id>"})
    if kind in {"place", "select_place", "disfield"}:
        formats.append(
            {
                "kind": "select_places",
                "places": [{"controller": 0, "location": "monster", "sequence": 0}],
            }
        )
    if kind in {"counter", "select_counter"}:
        formats.append(
            {
                "kind": "distribute_counters",
                "allocations": [{"candidate_id": "<候选 id>", "count": 1}],
            }
        )
    if kind == "announce_card":
        formats.append({"kind": "announce_card", "card_id": 12345678})
    return {
        "instruction": (
            "只输出以下适用于当前 prompt 的 intent 形状；"
            "尖括号是占位符，必须替换为实际值。严格满足 constraints。"
        ),
        "formats": formats,
        "constraints": constraints,
    }


class DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1, max_length=500)
    intent: dict[str, Any]


class ProbeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: bool


class DecisionFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


type ClientQuery = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class DecisionDeps:
    request: DecisionRequest
    delta: StateDelta
    store: StateDatabase
    skills: SkillResources
    settings: ServiceSettings
    query_client: ClientQuery
    deadline_monotonic: float
    prompt_text: str
    host_tool_attempts: int = 0
    client_queries: int = 0
    invalid_intents: int = 0
    validated_action: dict[str, Any] | None = None
    tool_records: list[dict[str, Any]] = field(default_factory=lambda: [])

    @property
    def identity(self) -> tuple[str, str, int]:
        data = self.request.data
        return (
            cast(str, data["session_id"]),
            cast(str, data["duel_id"]),
            cast(int, data["state_version"]),
        )

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline_monotonic:
            raise DecisionFailure("timeout", "decision deadline expired")

    def tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.check_deadline()
        self.host_tool_attempts += 1
        if self.host_tool_attempts > self.settings.limits.host_tool_attempts:
            raise DecisionFailure("budget_exhausted", "host tool attempt budget exhausted")
        record: dict[str, Any] = {
            "name": name,
            "args": args,
            "at_unix_ms": int(time.time() * 1000),
        }
        self.tool_records.append(record)
        return record

    def client_tool(self, name: str, args: dict[str, Any]) -> None:
        self.tool(name, args)
        self.client_queries += 1
        if self.client_queries > self.settings.limits.client_queries:
            raise DecisionFailure("budget_exhausted", "client query budget exhausted")


class DecisionAgent:
    """One service process owns one Pydantic AI agent and isolated duel histories."""

    def __init__(
        self,
        settings: ServiceSettings,
        store: StateDatabase,
        skills: SkillResources,
        *,
        model: Model | None = None,
    ) -> None:
        if settings.model is None:
            raise ValueError("Pydantic AI backend requires model settings")
        self.settings = settings
        self.model_settings = settings.model
        self.store = store
        self.hand_notes = HandNotes(store)
        self.skills = skills
        self.context = DuelContext(skills.root, store, skills)
        self._stream_capable = (
            not isinstance(model, FunctionModel) or model.stream_function is not None
        )
        if model is None:
            model = OpenAIResponsesModel(
                self.model_settings.name,
                provider=OpenAIProvider(
                    base_url=self.model_settings.base_url,
                    api_key=model_api_key(settings),
                ),
                profile={
                    "supports_forced_tool_choice": self.model_settings.supports_forced_tool_choice
                },
            )
        budgeted_model = BudgetModel(model)
        self.model = budgeted_model
        compaction_model_settings = self._request_settings()
        compaction_model_settings["timeout"] = settings.compaction.summary_timeout_seconds
        compaction = TieredCompaction(
            tiers=[
                ClearToolResults(max_tokens=1, keep_pairs=3),
                FallbackCompaction(
                    fallback_chain=[
                        SummarizingCompaction(
                            model=budgeted_model,
                            max_messages=1,
                            keep_tokens=int(
                                self.model_settings.context_window_tokens
                                * settings.compaction.target_fraction
                            ),
                            instructions=(
                                "概括较早的决斗计划和未知点。不要把推测写成事实；"
                                "精确保留决策相关标识，注明权威场面与历史需由工具重新查询。"
                            ),
                            model_settings=compaction_model_settings,
                        ),
                        SlidingWindowCompaction(
                            max_messages=1,
                            keep_tokens=int(
                                self.model_settings.context_window_tokens
                                * settings.compaction.target_fraction
                            ),
                        ),
                    ],
                ),
            ],
            target_fraction=settings.compaction.trigger_fraction,
            context_window=settings.model.context_window_tokens,
        )
        self.agent = Agent[DecisionDeps, DecisionOutput](
            budgeted_model,
            name="ygopro_duel_agent",
            deps_type=DecisionDeps,
            output_type=ToolOutput(DecisionOutput),
            retries=settings.limits.invalid_intent_attempts - 1,
            model_settings=OpenAIResponsesModelSettings(openai_store=self.model_settings.store),
            capabilities=[
                CodeMode(
                    tools=[
                        "rulebook_index",
                        "rulebook_section",
                        "card_by_id",
                        "cards_by_ids",
                        "search_cards",
                        "own_decklist",
                        "current_state",
                        "zone_state",
                        "card_state",
                        "event_history",
                        "read_zone_note",
                        "client_inspect_zone",
                        "client_inspect_card",
                    ],
                    max_tool_calls=settings.limits.host_tool_attempts,
                    resource_limits={"max_duration_secs": 10, "max_memory": 67_108_864},
                ),
                compaction,
            ],
        )
        self._register_tools()
        self._histories: dict[tuple[str, str], list[Any]] = {}

        @self.agent.instructions
        def duel_instructions(ctx: RunContext[DecisionDeps]) -> str:
            return ctx.deps.prompt_text

    def _request_settings(self) -> OpenAIResponsesModelSettings:
        model = self.model_settings
        options: dict[str, Any] = {"openai_store": model.store}
        if model.reasoning_effort != "auto":
            options["openai_reasoning_effort"] = model.reasoning_effort
        if model.effective_reasoning_summary != "off":
            options["openai_reasoning_summary"] = model.effective_reasoning_summary
        return OpenAIResponsesModelSettings(**options)

    async def probe(self) -> None:
        """Verify Responses tool calls and structured output before serving a live client."""
        probe_agent = Agent(
            self.model,
            instructions="调用 probe_echo(value='ready') 一次，然后以结构化输出返回 ok=true。",
            output_type=ToolOutput(ProbeOutput),
            model_settings=self._request_settings(),
            retries=0,
        )
        called = False

        @probe_agent.tool_plain
        def probe_echo(value: str) -> str:
            """Return the value unchanged for a local tool-call capability check."""
            nonlocal called
            called = True
            return value

        try:
            async with asyncio.timeout(self.settings.server.startup_timeout_seconds):
                result = await probe_agent.run(
                    "先调用 probe_echo，再返回 ok=true。",
                    usage_limits=UsageLimits(request_limit=3),
                )
        except TimeoutError as exc:
            raise DecisionFailure(
                "provider_unavailable", "model capability probe timed out"
            ) from exc
        except ModelAPIError as exc:
            raise DecisionFailure(
                "provider_unavailable",
                "model capability probe was rejected; check reasoning settings "
                "and provider support",
            ) from exc
        except Exception as exc:
            raise DecisionFailure("provider_unavailable", "model capability probe failed") from exc
        if not called or result.output.ok is not True:
            raise DecisionFailure(
                "provider_unavailable", "model lacks required tool/output support"
            )

    def _register_tools(self) -> None:
        agent = self.agent

        @agent.tool
        def rulebook_index(ctx: RunContext[DecisionDeps]) -> str:
            """List the available OCG rulebook topics before reading a section."""
            ctx.deps.tool("rulebook_index", {})
            return ctx.deps.skills.rulebook_index()

        @agent.tool
        def rulebook_section(ctx: RunContext[DecisionDeps], section: str) -> str:
            """Read one named OCG rulebook section, such as effects or game-progression."""
            ctx.deps.tool("rulebook_section", {"section": section})
            return ctx.deps.skills.rulebook_section(section)

        @agent.tool
        def card_by_id(ctx: RunContext[DecisionDeps], card_id: int) -> dict[str, Any]:
            """Read public card details by ID; returns id, name, card_type and effect_text."""
            ctx.deps.tool("card_by_id", {"card_id": card_id})
            return ctx.deps.skills.card_by_id(card_id)

        @agent.tool
        def cards_by_ids(
            ctx: RunContext[DecisionDeps], card_ids: list[int]
        ) -> list[dict[str, Any]]:
            """Read full details for distinct IDs; returns card objects in input order."""
            record = ctx.deps.tool("cards_by_ids", {"card_ids": card_ids})
            if not 1 <= len(card_ids) <= ctx.deps.settings.limits.card_lookup_batch_size:
                raise ValueError("card_ids exceeds configured batch size")
            started = time.perf_counter()
            result = ctx.deps.skills.cards_by_ids(card_ids)
            payload_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            metric = {
                "distinct_card_ids": len(card_ids),
                "result_bytes": payload_bytes,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            record.update(metric)
            telemetry = current_telemetry.get()
            if telemetry is not None:
                telemetry.emit("card_batch_lookup", metric)
            return result

        @agent.tool
        def search_cards(
            ctx: RunContext[DecisionDeps], keyword: str, limit: int = 30, offset: int = 0
        ) -> dict[str, Any]:
            """Search card text; returns {keyword, ids: list[int], total: int}."""
            ctx.deps.tool("search_cards", {"keyword": keyword, "limit": limit, "offset": offset})
            return ctx.deps.skills.search_cards(keyword, limit=limit, offset=offset)

        @agent.tool
        def own_decklist(ctx: RunContext[DecisionDeps]) -> dict[str, Any]:
            """Read own submitted main/extra deck catalog: card_id, count, name and card_type."""
            ctx.deps.tool("own_decklist", {})
            session, duel, _ = ctx.deps.identity
            return self.context.catalog(session, duel)

        @agent.tool
        def current_state(ctx: RunContext[DecisionDeps]) -> dict[str, Any]:
            """Read the complete, current confirmed visible field for this player."""
            ctx.deps.tool("current_state", {})
            session, duel, version = ctx.deps.identity
            return ctx.deps.store.get_state(session, duel, version)

        @agent.tool
        def zone_state(ctx: RunContext[DecisionDeps], player: int, zone: str) -> dict[str, Any]:
            """Read one confirmed visible zone; hidden cards remain hidden."""
            ctx.deps.tool("zone_state", {"player": player, "zone": zone})
            session, duel, version = ctx.deps.identity
            return ctx.deps.store.get_zone(session, duel, version, player, zone)

        @agent.tool
        def card_state(ctx: RunContext[DecisionDeps], instance_id: str) -> dict[str, Any]:
            """Read a card at a current visible position key, if still present."""
            ctx.deps.tool("card_state", {"instance_id": instance_id})
            session, duel, version = ctx.deps.identity
            state = ctx.deps.store.get_state(session, duel, version)
            for zone in cast(list[dict[str, Any]], state["zones"]):
                for card in zone["cards"]:
                    if card["instance_id"] == instance_id:
                        return card
            raise StateError("card_not_found", "card position is not visible")

        @agent.tool
        def event_history(
            ctx: RunContext[DecisionDeps], after_event_id: int = 0, limit: int = 50
        ) -> dict[str, Any]:
            """Read a page of confirmed observed events for this player."""
            ctx.deps.tool("event_history", {"after_event_id": after_event_id, "limit": limit})
            session, duel, version = ctx.deps.identity
            events = ctx.deps.store.get_events(
                session,
                duel,
                state_version=version,
                after_event_id=after_event_id,
                limit=min(limit, 100),
            )
            return {"state_version": version, "after_event_id": after_event_id, "events": events}

        @agent.tool
        def read_zone_note(
            ctx: RunContext[DecisionDeps], player: int = 1, zone: str = "hand"
        ) -> dict[str, Any]:
            """Read this Agent's current inference about the opponent hand."""
            ctx.deps.tool("read_zone_note", {"player": player, "zone": zone})
            if type(player) is not int or player != 1 or zone != "hand":
                return {"ok": False, "error": "only the opponent hand is supported"}
            session, duel, _ = ctx.deps.identity
            note = self.hand_notes.current(session, duel, ctx.deps.delta.ack_event_id)
            return {"ok": True, **note}

        @agent.tool
        def write_zone_note(
            ctx: RunContext[DecisionDeps],
            player: int,
            zone: str,
            note: str,
            evidence_event_ids: list[int],
        ) -> dict[str, Any]:
            """Replace the current opponent-hand inference and retain its old revision."""
            ctx.deps.tool(
                "write_zone_note",
                {"player": player, "zone": zone, "evidence_event_ids": evidence_event_ids},
            )
            session, duel, version = ctx.deps.identity
            try:
                value = self.hand_notes.write(
                    session,
                    duel,
                    version,
                    ctx.deps.delta.ack_event_id,
                    player,
                    zone,
                    note,
                    evidence_event_ids,
                )
            except StateError as exc:
                return {"ok": False, "error": exc.code, "message": str(exc)}
            return {"ok": True, **value}

        @agent.tool
        async def client_inspect_zone(
            ctx: RunContext[DecisionDeps], player: int, zone: str
        ) -> dict[str, Any]:
            """Ask the client for a currently inspectable zone missing from the mirror."""
            ctx.deps.client_tool("client_inspect_zone", {"player": player, "zone": zone})
            return await ctx.deps.query_client(
                {"kind": "inspect_zone", "player": player, "zone": zone}
            )

        @agent.tool
        async def client_inspect_card(
            ctx: RunContext[DecisionDeps], instance_id: str
        ) -> dict[str, Any]:
            """Ask the client for currently inspectable fields of one position key."""
            ctx.deps.client_tool("client_inspect_card", {"instance_id": instance_id})
            return await ctx.deps.query_client({"kind": "inspect_card", "instance_id": instance_id})

        @agent.output_validator
        def validate_output(
            ctx: RunContext[DecisionDeps], output: DecisionOutput
        ) -> DecisionOutput:
            started = time.perf_counter()
            valid = False
            try:
                ctx.deps.validated_action = translate_intent(ctx.deps.request, output.intent)
                valid = True
            except ContractError as exc:
                ctx.deps.invalid_intents += 1
                raise ModelRetry(f"非法语义动作：{exc}。请只从当前合法候选选择。") from exc
            finally:
                telemetry = current_telemetry.get()
                if telemetry is not None:
                    telemetry.emit(
                        "intent_validation_timing",
                        {
                            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                            "valid": valid,
                        },
                    )
            return output

    def _load_history(self, session: str, duel: str) -> list[Any]:
        key = (session, duel)
        if key in self._histories:
            return self._histories[key]
        after_id = 0
        latest: dict[str, Any] | None = None
        while True:
            page = self.store.get_records(
                session, duel, after_id=after_id, limit=100, kind="model_context"
            )
            if not page:
                break
            latest = cast(dict[str, Any], page[-1]["payload"])
            after_id = cast(int, page[-1]["id"])
            if len(page) < 100:
                break
        history = ModelMessagesTypeAdapter.validate_python(latest["messages"]) if latest else []
        self._histories[key] = history
        return history

    async def decide(
        self,
        request: DecisionRequest,
        delta: StateDelta,
        query_client: ClientQuery,
    ) -> tuple[dict[str, Any], str]:
        data = request.data
        session, duel = cast(str, data["session_id"]), cast(str, data["duel_id"])
        deadline_ms = cast(int, data["deadline_unix_ms"])
        remaining = (deadline_ms - int(time.time() * 1000)) / 1000
        if remaining <= 0:
            raise DecisionFailure("timeout", "decision deadline expired")
        self.context.ensure(request)
        pinned_prompt = self.context.prompt(session, duel)
        deps = DecisionDeps(
            request,
            delta,
            self.store,
            self.skills,
            self.settings,
            query_client,
            time.monotonic() + remaining,
            pinned_prompt["text"],
        )
        history = self._load_history(session, duel)
        prompt_payload: dict[str, Any] = {
            "state_version": data["state_version"],
            "ack_event_id": delta.ack_event_id,
            "new_events": delta.events,
            "net_changes": delta.changes,
            "opponent_hand_note": self.hand_notes.current(session, duel, delta.ack_event_id),
            "prompt": data["prompt"],
            "intent_format": intent_format(request),
            "budget": {
                "model_requests": self.settings.limits.model_requests,
                "host_tool_attempts": self.settings.limits.host_tool_attempts,
                "client_queries": self.settings.limits.client_queries,
                "deadline_unix_ms": deadline_ms,
            },
        }
        if not history:
            # The first model turn has no prior field context. Supply the exact
            # confirmed, perspective-scoped snapshot once; later turns use deltas.
            prompt_payload["initial_state"] = self.store.get_state(
                session, duel, cast(int, data["state_version"])
            )
            prompt_payload["own_deck_catalog"] = self.context.catalog(session, duel)
        prompt = json.dumps(
            prompt_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        turn_id = f"{data['prompt_id']}:{data['state_version']}"
        trace = TraceWriter(self.store, session, duel, turn_id)
        started = time.perf_counter()
        trace.emit(
            "model_request_started",
            {
                "prompt": json.loads(prompt),
                "history_messages": len(history),
                "duel_prompt_sha256": pinned_prompt["sha256"],
                "reasoning_effort_configured": self.model_settings.reasoning_effort,
                "reasoning_effort_requested": (
                    None
                    if self.model_settings.reasoning_effort == "auto"
                    else self.model_settings.reasoning_effort
                ),
                "reasoning_summary_configured": self.model_settings.reasoning_summary,
                "reasoning_summary_requested": self.model_settings.effective_reasoning_summary,
            },
        )
        token = current_budget.set(
            ModelBudget(
                self.settings.limits.model_requests,
                time.monotonic() + remaining,
                self.settings.limits.finalization_reserve_requests,
                self.settings.limits.finalization_reserve_seconds,
            )
        )
        telemetry = ModelTelemetry(lambda kind, payload: trace.emit(kind, payload, response_id=""))
        telemetry_token = current_telemetry.set(telemetry)
        try:
            async with asyncio.timeout(remaining):
                result = None
                model_settings = self._request_settings()
                limits = UsageLimits(
                    request_limit=self.settings.limits.model_requests,
                    tool_calls_limit=self.settings.limits.host_tool_attempts,
                )
                if self._stream_capable:
                    async with self.agent.run_stream_events(
                        prompt,
                        deps=deps,
                        message_history=history,
                        model_settings=model_settings,
                        usage_limits=limits,
                    ) as events:
                        async for event in events:
                            if isinstance(event, AgentRunResultEvent):
                                result = event.result
                            else:
                                trace.accept(event)
                else:
                    trace.start_response()
                    result = await self.agent.run(
                        prompt,
                        deps=deps,
                        message_history=history,
                        model_settings=model_settings,
                        usage_limits=limits,
                    )
                if result is None:
                    raise DecisionFailure("internal_error", "model stream ended without a result")
                trace.finish_response()
        except TimeoutError as exc:
            raise DecisionFailure("timeout", "decision deadline expired") from exc
        except UsageLimitExceeded as exc:
            raise DecisionFailure("budget_exhausted", "model or tool budget exhausted") from exc
        except ModelAPIError as exc:
            raise DecisionFailure("provider_unavailable", "model provider request failed") from exc
        except UnexpectedModelBehavior as exc:
            raise DecisionFailure("invalid_intent", "model exceeded validation retries") from exc
        except RuntimeError as exc:
            if str(exc) == "model request budget exhausted":
                raise DecisionFailure("budget_exhausted", str(exc)) from exc
            raise
        finally:
            trace.flush()
            trace.emit(
                "model_run_timing",
                {"duration_ms": round((time.perf_counter() - started) * 1000, 2)},
            )
            current_telemetry.reset(telemetry_token)
            current_budget.reset(token)
        if deps.validated_action is None:
            raise DecisionFailure("invalid_intent", "model returned no validated action")
        record_id = f"{data['prompt_id']}:{data['state_version']}"
        persistence_started = time.perf_counter()
        self.store.append_record(
            session,
            duel,
            "model_exchange",
            record_id,
            {
                "new_messages": ModelMessagesTypeAdapter.dump_python(
                    result.new_messages(), mode="json"
                ),
                "tool_attempts": deps.tool_records,
                "reason": result.output.reason,
                "intent": result.output.intent,
                "action": deps.validated_action,
            },
        )
        compacted = ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json")
        self.store.append_record(session, duel, "model_context", record_id, {"messages": compacted})
        trace.emit(
            "model_decision",
            {
                "reason": result.output.reason,
                "intent": result.output.intent,
                "action": deps.validated_action,
                "tool_attempts": deps.tool_records,
            },
        )
        self._histories[(session, duel)] = result.all_messages()
        trace.emit(
            "decision_timing",
            {
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "persistence_ms": round((time.perf_counter() - persistence_started) * 1000, 2),
                "status": "completed",
                "reasoning_forms_returned": sorted(trace.reasoning_forms),
                "provider_request_count": telemetry.next_index,
                "invalid_intent_attempts": deps.invalid_intents,
                "host_tool_attempts": deps.host_tool_attempts,
                "client_queries": deps.client_queries,
            },
        )
        return deps.validated_action, result.output.reason
