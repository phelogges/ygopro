"""Enforce one decision's model request budget across Agent and compaction calls."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai.messages import InstructionPart, ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


@dataclass(slots=True)
class ModelBudget:
    requests_remaining: int
    deadline_monotonic: float
    reserve_requests: int = 0
    reserve_seconds: int = 0


current_budget: ContextVar[ModelBudget | None] = ContextVar("ygopro_model_budget", default=None)


def _usage_counts(usage: RequestUsage) -> dict[str, int]:
    return {
        "input_count": usage.input_tokens,
        "output_count": usage.output_tokens,
        "cached_input_count": usage.cache_read_tokens,
        "reasoning_count": usage.details.get("reasoning_tokens", 0),
    }


@dataclass(slots=True)
class ModelTelemetry:
    emit: Callable[[str, dict[str, Any]], None]
    next_index: int = 0
    active_index: int | None = None
    started: dict[int, float] = field(default_factory=lambda: dict[int, float]())
    first_text: set[int] = field(default_factory=lambda: set[int]())

    def start(self) -> int:
        self.next_index += 1
        index = self.next_index
        self.started[index] = time.perf_counter()
        self.active_index = index
        self.emit("provider_request_started", {"request_number": index})
        return index

    def mark_text(self, source: str) -> None:
        index = self.active_index
        if index is None or index in self.first_text:
            return
        self.first_text.add(index)
        self.emit(
            "provider_first_text",
            {
                "request_number": index,
                "source": source,
                "elapsed_ms": round((time.perf_counter() - self.started[index]) * 1000, 2),
            },
        )

    def finish(
        self,
        index: int,
        *,
        usage: RequestUsage | None = None,
        first_event_seconds: float | None = None,
        error: BaseException | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "request_number": index,
            "duration_ms": round((time.perf_counter() - self.started[index]) * 1000, 2),
            "first_event_ms": round(first_event_seconds * 1000, 2)
            if first_event_seconds is not None
            else None,
            "first_text_seen": index in self.first_text,
            "status": "error" if error else "completed",
        }
        if usage is not None and (
            usage.input_tokens or usage.output_tokens or usage.details or usage.cache_read_tokens
        ):
            payload["usage"] = _usage_counts(usage)
        else:
            payload["usage"] = None
        if error is not None:
            payload["error_type"] = type(error).__name__
        self.emit("provider_request_finished", payload)
        if self.active_index == index:
            self.active_index = None


current_telemetry: ContextVar[ModelTelemetry | None] = ContextVar(
    "ygopro_model_telemetry", default=None
)


class BudgetModel(WrapperModel):
    def __init__(self, wrapped: Model) -> None:
        super().__init__(wrapped)

    @staticmethod
    def _budgeted_settings(model_settings: ModelSettings | None) -> ModelSettings | None:
        budget = current_budget.get()
        if budget is None:
            return model_settings
        remaining = budget.deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("decision deadline expired")
        if budget.requests_remaining <= 0:
            raise RuntimeError("model request budget exhausted")
        budget.requests_remaining -= 1
        effective: dict[str, Any] = dict(model_settings or {})
        configured = effective.get("timeout")
        if isinstance(configured, (int, float)):
            remaining = min(remaining, configured)
        effective["timeout"] = remaining
        return ModelSettings(**effective)

    @staticmethod
    def _finalization_parameters(parameters: ModelRequestParameters) -> ModelRequestParameters:
        budget = current_budget.get()
        if budget is None or not parameters.output_tools:
            return parameters
        remaining_seconds = budget.deadline_monotonic - time.monotonic()
        finalizing = (
            budget.reserve_requests > 0 and budget.requests_remaining <= budget.reserve_requests
        ) or (budget.reserve_seconds > 0 and remaining_seconds <= budget.reserve_seconds)
        if not finalizing:
            return parameters
        telemetry = current_telemetry.get()
        if telemetry is not None:
            telemetry.emit(
                "finalization_guard",
                {
                    "requests_remaining": budget.requests_remaining,
                    "seconds_remaining": round(remaining_seconds, 2),
                },
            )
        return replace(
            parameters,
            function_tools=[],
            native_tools=[],
            instruction_parts=[
                *(parameters.instruction_parts or []),
                InstructionPart(
                    content="工具预算已进入最终化阶段。现在只能从当前合法候选提交最终语义动作与简短理由。"
                ),
            ],
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        parameters = self._finalization_parameters(model_request_parameters)
        settings = self._budgeted_settings(model_settings)
        telemetry = current_telemetry.get()
        index = telemetry.start() if telemetry else None
        try:
            response = await self.wrapped.request(messages, settings, parameters)
        except BaseException as exc:
            if telemetry is not None and index is not None:
                telemetry.finish(index, error=exc)
            raise
        if telemetry is not None and index is not None:
            telemetry.finish(index, usage=response.usage)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        parameters = self._finalization_parameters(model_request_parameters)
        settings = self._budgeted_settings(model_settings)
        telemetry = current_telemetry.get()
        index = telemetry.start() if telemetry else None
        started = time.perf_counter()
        stream: StreamedResponse | None = None
        error: BaseException | None = None
        try:
            async with self.wrapped.request_stream(
                messages, settings, parameters, run_context
            ) as stream:
                yield stream
        except BaseException as exc:
            error = exc
            raise
        finally:
            if telemetry is not None and index is not None:
                telemetry.finish(
                    index,
                    usage=stream.usage if stream is not None else None,
                    first_event_seconds=stream.time_to_first_chunk(started)
                    if stream is not None
                    else None,
                    error=error,
                )
