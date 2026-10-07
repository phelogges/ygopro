"""Enforce one decision's model request budget across Agent and compaction calls."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings


@dataclass(slots=True)
class ModelBudget:
    requests_remaining: int
    deadline_monotonic: float


current_budget: ContextVar[ModelBudget | None] = ContextVar("ygopro_model_budget", default=None)


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

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        return await self.wrapped.request(
            messages, self._budgeted_settings(model_settings), model_request_parameters
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        async with self.wrapped.request_stream(
            messages, self._budgeted_settings(model_settings), model_request_parameters, run_context
        ) as stream:
            yield stream
