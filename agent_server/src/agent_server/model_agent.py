"""Pydantic AI decision runner and perspective-scoped read-only tools."""

import asyncio
import json
import time
from typing import Any, cast

from agent_sdk.contract import ContractError, DecisionRequest, translate_intent
from agent_sdk.state import StateDelta
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
from agent_server.duel_tools import (
    TOOLSET_VERSION,
    ClientQuery,
    DecisionDeps,
    DecisionFailure,
    DuelTools,
)
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase
from agent_server.trace import TraceWriter


def model_visible_prompt(request: DecisionRequest) -> dict[str, Any]:
    """Keep large deterministic validation sets out of model context."""
    prompt: dict[str, Any] = dict(request.prompt)
    if prompt["kind"] == "announce_card":
        constraints = dict(cast(dict[str, Any], prompt["constraints"]))
        allowed = constraints.pop("allowed_card_ids", None)
        if isinstance(allowed, list):
            constraints["allowed_card_count"] = len(cast(list[Any], allowed))
        prompt["constraints"] = constraints
    return prompt


def intent_format(request: DecisionRequest) -> dict[str, Any]:
    """Describe the action shapes accepted by the deterministic SDK translator."""
    kind = request.prompt["kind"]
    constraints = model_visible_prompt(request)["constraints"]
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
        self.skills = skills
        self.context = DuelContext(skills.root, store, skills)
        self.tools = DuelTools(self.context)
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
        compaction_model_settings["timeout"] = (
            self.model_settings.compaction.summary_timeout_seconds
        )
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
                                * self.model_settings.compaction.target_fraction
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
                                * self.model_settings.compaction.target_fraction
                            ),
                        ),
                    ],
                ),
            ],
            target_fraction=self.model_settings.compaction.trigger_fraction,
            context_window=self.model_settings.context_window_tokens,
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
                        "search_card_descriptions",
                        "search_card_names",
                        "own_decklist",
                        "current_state",
                        "zone_state",
                        "card_state",
                        "event_history",
                        "calculate",
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
            return self.tools.rulebook_index(ctx.deps)

        @agent.tool
        def rulebook_section(ctx: RunContext[DecisionDeps], section: str) -> str:
            """Read one named OCG rulebook section, such as effects or game-progression."""
            return self.tools.rulebook_section(ctx.deps, section)

        @agent.tool
        def card_by_id(ctx: RunContext[DecisionDeps], card_id: int) -> dict[str, Any]:
            """Read public card details by ID; returns id, name, card_type and effect_text."""
            return self.tools.card_by_id(ctx.deps, card_id)

        @agent.tool
        def cards_by_ids(
            ctx: RunContext[DecisionDeps], card_ids: list[int]
        ) -> list[dict[str, Any]]:
            """Read full details for distinct IDs; returns card objects in input order."""
            return self.tools.cards_by_ids(ctx.deps, card_ids)

        @agent.tool
        def search_card_descriptions(
            ctx: RunContext[DecisionDeps], keyword: str, limit: int = 30, offset: int = 0
        ) -> dict[str, Any]:
            """Search card description/effect text, not names; returns {keyword, ids, total}."""
            return self.tools.search_card_descriptions(ctx.deps, keyword, limit, offset)

        @agent.tool
        def search_card_names(
            ctx: RunContext[DecisionDeps], keyword: str, limit: int = 30, offset: int = 0
        ) -> dict[str, Any]:
            """Search card names; returns {keyword, matches: [{card_id, name}], total}."""
            return self.tools.search_card_names(ctx.deps, keyword, limit, offset)

        @agent.tool
        def own_decklist(ctx: RunContext[DecisionDeps]) -> dict[str, Any]:
            """Read own submitted main/extra deck catalog: card_id, count, name and card_type."""
            return self.tools.own_decklist(ctx.deps)

        @agent.tool
        def current_state(ctx: RunContext[DecisionDeps]) -> dict[str, Any]:
            """Read the complete, current confirmed visible field for this player."""
            return self.tools.current_state(ctx.deps)

        @agent.tool
        def zone_state(ctx: RunContext[DecisionDeps], player: int, zone: str) -> dict[str, Any]:
            """Read one confirmed visible zone; hidden cards remain hidden."""
            return self.tools.zone_state(ctx.deps, player, zone)

        @agent.tool
        def card_state(ctx: RunContext[DecisionDeps], instance_id: str) -> dict[str, Any]:
            """Read a card at a current visible position key, if still present."""
            return self.tools.card_state(ctx.deps, instance_id)

        @agent.tool
        def event_history(
            ctx: RunContext[DecisionDeps], after_event_id: int = 0, limit: int = 50
        ) -> dict[str, Any]:
            """Read a page of confirmed observed events for this player."""
            return self.tools.event_history(ctx.deps, after_event_id, limit)

        @agent.tool
        def calculate(
            ctx: RunContext[DecisionDeps],
            operation: str,
            left: int | float | str,
            right: int | float | str,
        ) -> dict[str, str]:
            """Calculate bounded decimal add, subtract, multiply, divide, or compare."""
            return self.tools.calculate(ctx.deps, operation, left, right)

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
        history = (
            ModelMessagesTypeAdapter.validate_python(latest["messages"])
            if latest and latest.get("toolset_version") == TOOLSET_VERSION
            else []
        )
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

        def emit_tool_metric(kind: str, payload: dict[str, Any]) -> None:
            telemetry = current_telemetry.get()
            if telemetry is not None:
                telemetry.emit(kind, payload)

        deps.emit_tool_metric = emit_tool_metric
        history = self._load_history(session, duel)
        prompt_payload: dict[str, Any] = {
            "state_version": data["state_version"],
            "ack_event_id": delta.ack_event_id,
            "new_events": delta.events,
            "net_changes": delta.changes,
            "prompt": model_visible_prompt(request),
            "intent_format": intent_format(request),
            "budget": {
                "model_requests": self.settings.limits.model_requests,
                "host_tool_attempts": self.settings.limits.host_tool_attempts,
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
        self.store.append_record(
            session,
            duel,
            "model_context",
            record_id,
            {"toolset_version": TOOLSET_VERSION, "messages": compacted},
        )
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
