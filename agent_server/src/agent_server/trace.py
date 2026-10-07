"""Small, explicit public projection of model events for the human timeline."""

from __future__ import annotations

import re
import time
from typing import Any, cast

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    OutputToolCallEvent,
    OutputToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)

from agent_server.storage import StateDatabase

MAX_TEXT = 32_768
MAX_ARGUMENTS = 16_384


def safe_value(value: object, *, max_length: int = MAX_ARGUMENTS, depth: int = 0) -> object:
    """Bound JSON-like tool values; never serialize provider metadata or signatures."""
    if depth >= 16:
        return "[nesting truncated]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_length else value[:max_length] + "[truncated]"
    if isinstance(value, list | tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        result = [
            safe_value(item, max_length=max_length, depth=depth + 1) for item in sequence[:100]
        ]
        if len(sequence) > 100:
            result.append("[items truncated]")
        return result
    if isinstance(value, dict):
        document = cast(dict[object, object], value)
        result = {
            str(key)[:128]: safe_value(item, max_length=max_length, depth=depth + 1)
            for key, item in list(document.items())[:100]
            if not re.search(
                r"signature|provider_details|encrypted|api[_-]?key|token|secret|password|authorization",
                str(key),
                re.IGNORECASE,
            )
        }
        if len(document) > 100:
            result["_truncated"] = True
        return result
    return f"[unserializable {type(value).__name__}]"


class TraceWriter:
    """Persist user-visible event stages and bounded text chunks."""

    def __init__(self, store: StateDatabase, session: str, duel: str, turn_id: str) -> None:
        self.store = store
        self.session = session
        self.duel = duel
        self.turn_id = turn_id
        self.response_number = 0
        self.response_id: str | None = None
        self._text_source: str | None = None
        self._text_form: str | None = None
        self._text_parts: list[str] = []
        self._last_flush = time.monotonic()

    def emit(self, kind: str, payload: dict[str, Any], *, response_id: str | None = None) -> None:
        self.flush()
        self.store.add_trace(
            self.session,
            self.duel,
            self.turn_id,
            response_id if response_id is not None else self.response_id,
            kind,
            cast(dict[str, object], safe_value(payload)),
        )

    def flush(self) -> None:
        if not self._text_parts or self._text_source is None:
            return
        self.store.add_trace(
            self.session,
            self.duel,
            self.turn_id,
            self.response_id,
            "content_delta",
            {
                "source": self._text_source,
                "form": self._text_form,
                "text": "".join(self._text_parts),
            },
        )
        self._text_parts.clear()
        self._last_flush = time.monotonic()

    def text(self, source: str, content: str, *, form: str | None = None) -> None:
        if not content:
            return
        if self._text_source != source or self._text_form != form:
            self.flush()
            self._text_source = source
            self._text_form = form
        for start in range(0, len(content), MAX_TEXT):
            self._text_parts.append(content[start : start + MAX_TEXT])
            if (
                sum(map(len, self._text_parts)) >= 4096
                or time.monotonic() - self._last_flush >= 0.25
            ):
                self.flush()

    def start_response(self) -> None:
        self.finish_response()
        self.flush()
        self.response_number += 1
        self.response_id = f"{self.turn_id}:r{self.response_number}"
        self.emit("model_response_started", {"response_number": self.response_number})

    def finish_response(self) -> None:
        if self.response_id is not None:
            self.emit("model_response_finished", {"response_number": self.response_number})
            self.response_id = None

    def accept(self, event: object) -> None:
        """Project Pydantic events using an allowlist of known public fields."""
        if isinstance(event, PartStartEvent):
            if event.index == 0 or self.response_id is None:
                self.start_response()
            part = event.part
            if isinstance(part, ThinkingPart):
                details = cast(dict[str, object], part.provider_details or {})
                raw = "raw_content" in details
                self.text(
                    "provider_reasoning", part.content or "", form="text" if raw else "summary"
                )
            elif isinstance(part, TextPart):
                self.text("assistant_text", part.content)
        elif isinstance(event, PartDeltaEvent):
            delta = event.delta
            if isinstance(delta, ThinkingPartDelta):
                details = cast(dict[str, object], delta.provider_details or {})
                raw = "raw_content" in details
                self.text(
                    "provider_reasoning",
                    delta.content_delta or "",
                    form="text" if raw else "summary",
                )
            elif isinstance(delta, TextPartDelta):
                self.text("assistant_text", delta.content_delta)
        elif isinstance(event, PartEndEvent):
            self.flush()
            part = event.part
            if isinstance(part, ToolCallPart):
                self.emit(
                    "model_tool_call",
                    {
                        "tool_name": part.tool_name,
                        "tool_call_id": part.tool_call_id,
                        "args": safe_value(part.args),
                    },
                )
        elif isinstance(event, FunctionToolCallEvent | OutputToolCallEvent):
            self.emit(
                "tool_started",
                {
                    "tool_name": event.part.tool_name,
                    "tool_call_id": event.part.tool_call_id,
                    "args": safe_value(event.part.args),
                },
            )
        elif isinstance(event, FunctionToolResultEvent):
            self.emit(
                "tool_finished",
                {
                    "tool_name": event.part.tool_name,
                    "tool_call_id": event.part.tool_call_id,
                    "result": safe_value(event.content),
                },
            )
        elif isinstance(event, OutputToolResultEvent):
            self.emit(
                "output_validated",
                {
                    "tool_name": event.part.tool_name,
                    "tool_call_id": event.part.tool_call_id,
                },
            )
