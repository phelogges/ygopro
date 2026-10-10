"""Backend-neutral decision context and duel tool execution."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from agent_sdk.contract import DecisionRequest
from agent_sdk.state import StateDelta, StateError

from agent_server.config import ServiceSettings
from agent_server.duel_context import DuelContext
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase
from agent_server.zone_notes import ZoneNotes

type ClientQuery = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
type MetricSink = Callable[[str, dict[str, Any]], None]


class DecisionFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    emit_tool_metric: MetricSink | None = None
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


class DuelTools:
    """Execute one perspective's tools with a fresh decision context per call."""

    def __init__(self, context: DuelContext, zone_notes: ZoneNotes) -> None:
        self.context = context
        self.zone_notes = zone_notes

    def rulebook_index(self, deps: DecisionDeps) -> str:
        deps.tool("rulebook_index", {})
        return deps.skills.rulebook_index()

    def rulebook_section(self, deps: DecisionDeps, section: str) -> str:
        deps.tool("rulebook_section", {"section": section})
        return deps.skills.rulebook_section(section)

    def card_by_id(self, deps: DecisionDeps, card_id: int) -> dict[str, Any]:
        deps.tool("card_by_id", {"card_id": card_id})
        return deps.skills.card_by_id(card_id)

    def cards_by_ids(self, deps: DecisionDeps, card_ids: list[int]) -> list[dict[str, Any]]:
        record = deps.tool("cards_by_ids", {"card_ids": card_ids})
        if not 1 <= len(card_ids) <= deps.settings.limits.card_lookup_batch_size:
            raise ValueError("card_ids exceeds configured batch size")
        started = time.perf_counter()
        result = deps.skills.cards_by_ids(card_ids)
        metric = {
            "distinct_card_ids": len(card_ids),
            "result_bytes": len(json.dumps(result, ensure_ascii=False).encode("utf-8")),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        record.update(metric)
        if deps.emit_tool_metric is not None:
            deps.emit_tool_metric("card_batch_lookup", metric)
        return result

    def search_cards(
        self, deps: DecisionDeps, keyword: str, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        deps.tool("search_cards", {"keyword": keyword, "limit": limit, "offset": offset})
        return deps.skills.search_cards(keyword, limit=limit, offset=offset)

    def own_decklist(self, deps: DecisionDeps) -> dict[str, Any]:
        deps.tool("own_decklist", {})
        session, duel, _ = deps.identity
        return self.context.catalog(session, duel)

    def current_state(self, deps: DecisionDeps) -> dict[str, Any]:
        deps.tool("current_state", {})
        session, duel, version = deps.identity
        return deps.store.get_state(session, duel, version)

    def zone_state(self, deps: DecisionDeps, player: int, zone: str) -> dict[str, Any]:
        deps.tool("zone_state", {"player": player, "zone": zone})
        session, duel, version = deps.identity
        return deps.store.get_zone(session, duel, version, player, zone)

    def card_state(self, deps: DecisionDeps, instance_id: str) -> dict[str, Any]:
        deps.tool("card_state", {"instance_id": instance_id})
        session, duel, version = deps.identity
        state = deps.store.get_state(session, duel, version)
        for zone in cast(list[dict[str, Any]], state["zones"]):
            for card in cast(list[dict[str, Any]], zone["cards"]):
                if card["instance_id"] == instance_id:
                    return card
        raise StateError("card_not_found", "card position is not visible")

    def event_history(
        self, deps: DecisionDeps, after_event_id: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        deps.tool("event_history", {"after_event_id": after_event_id, "limit": limit})
        if after_event_id < 0 or limit < 1:
            raise ValueError("invalid history page")
        session, duel, version = deps.identity
        events = deps.store.get_events(
            session,
            duel,
            state_version=version,
            after_event_id=after_event_id,
            limit=min(limit, 100),
        )
        return {"state_version": version, "after_event_id": after_event_id, "events": events}

    def read_zone_note(
        self, deps: DecisionDeps, player: int = 1, zone: str = "hand", sequence: int | None = None
    ) -> dict[str, Any]:
        deps.tool("read_zone_note", {"player": player, "zone": zone, "sequence": sequence})
        session, duel, _ = deps.identity
        try:
            note = self.zone_notes.current(
                session, duel, deps.delta.ack_event_id, player, zone, sequence
            )
        except StateError as exc:
            return {"ok": False, "error": exc.code, "message": str(exc)}
        return {"ok": True, **note}

    def write_zone_note(
        self,
        deps: DecisionDeps,
        player: int,
        zone: str,
        note: str,
        evidence_event_ids: list[int],
        sequence: int | None = None,
    ) -> dict[str, Any]:
        deps.tool(
            "write_zone_note",
            {
                "player": player,
                "zone": zone,
                "sequence": sequence,
                "evidence_event_ids": evidence_event_ids,
            },
        )
        session, duel, version = deps.identity
        try:
            value = self.zone_notes.write(
                session,
                duel,
                version,
                deps.delta.ack_event_id,
                player,
                zone,
                note,
                evidence_event_ids,
                sequence,
            )
        except StateError as exc:
            return {"ok": False, "error": exc.code, "message": str(exc)}
        return {"ok": True, **value}

    async def client_inspect_zone(
        self, deps: DecisionDeps, player: int, zone: str
    ) -> dict[str, Any]:
        deps.client_tool("client_inspect_zone", {"player": player, "zone": zone})
        return await deps.query_client({"kind": "inspect_zone", "player": player, "zone": zone})

    async def client_inspect_card(self, deps: DecisionDeps, instance_id: str) -> dict[str, Any]:
        deps.client_tool("client_inspect_card", {"instance_id": instance_id})
        return await deps.query_client({"kind": "inspect_card", "instance_id": instance_id})

    def calculate(
        self, deps: DecisionDeps, operation: str, left: int | float | str, right: int | float | str
    ) -> dict[str, str]:
        deps.tool("calculate", {"operation": operation, "left": left, "right": right})
        values: list[Decimal] = []
        for raw in (left, right):
            if type(raw) not in (int, float, str) or len(str(raw)) > 80:
                raise ValueError("operand must be a finite decimal")
            try:
                value = Decimal(str(raw))
            except InvalidOperation as exc:
                raise ValueError("operand must be a finite decimal") from exc
            if not value.is_finite() or abs(value) > 1_000_000_000:
                raise ValueError("operand outside supported range")
            values.append(value)
        first, second = values
        if operation == "add":
            result = first + second
        elif operation == "subtract":
            result = first - second
        elif operation == "multiply":
            result = first * second
        elif operation == "divide":
            if second == 0:
                raise ValueError("division by zero")
            result = first / second
        elif operation == "compare":
            return {"result": "-1" if first < second else "1" if first > second else "0"}
        else:
            raise ValueError("unknown calculation operation")
        return {"result": format(result, "f")}

    async def invoke(self, deps: DecisionDeps, name: str, args: dict[str, Any]) -> Any:
        """Translate an MCP tool call into the same methods used by Pydantic AI."""
        if name == "rulebook_index":
            return self.rulebook_index(deps)
        if name == "rulebook_section":
            return self.rulebook_section(deps, cast(str, args["section"]))
        if name == "card_by_id":
            return self.card_by_id(deps, cast(int, args["card_id"]))
        if name == "cards_by_ids":
            return self.cards_by_ids(deps, cast(list[int], args["card_ids"]))
        if name == "search_cards":
            return self.search_cards(
                deps,
                cast(str, args["keyword"]),
                cast(int, args.get("limit", 30)),
                cast(int, args.get("offset", 0)),
            )
        if name == "own_decklist":
            return self.own_decklist(deps)
        if name == "current_state":
            return self.current_state(deps)
        if name == "zone_state":
            return self.zone_state(deps, cast(int, args["player"]), cast(str, args["zone"]))
        if name == "card_state":
            return self.card_state(deps, cast(str, args["instance_id"]))
        if name == "event_history":
            return self.event_history(
                deps, cast(int, args.get("after_event_id", 0)), cast(int, args.get("limit", 50))
            )
        if name == "read_zone_note":
            return self.read_zone_note(
                deps,
                cast(int, args.get("player", 1)),
                cast(str, args.get("zone", "hand")),
                cast(int | None, args.get("sequence")),
            )
        if name == "write_zone_note":
            return self.write_zone_note(
                deps,
                cast(int, args["player"]),
                cast(str, args["zone"]),
                cast(str, args["note"]),
                cast(list[int], args["evidence_event_ids"]),
                cast(int | None, args.get("sequence")),
            )
        if name == "client_inspect_zone":
            return await self.client_inspect_zone(
                deps, cast(int, args["player"]), cast(str, args["zone"])
            )
        if name == "client_inspect_card":
            return await self.client_inspect_card(deps, cast(str, args["instance_id"]))
        if name == "calculate":
            return self.calculate(
                deps,
                cast(str, args["operation"]),
                cast(int | float | str, args["left"]),
                cast(int | float | str, args["right"]),
            )
        raise ValueError("unknown tool")
