"""In-memory v3 decision stages; durable facts remain in StateDatabase."""

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from agent_sdk.contract import DecisionRequest
from agent_sdk.state import StateDelta

from agent_server.model_agent import DecisionFailure
from agent_server.storage import StateDatabase

type DecisionKey = tuple[str, str, int, int]
type DecideFunction = Callable[
    [DecisionRequest, StateDelta, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]],
    Awaitable[tuple[dict[str, Any], str]],
]
VISIBLE_ZONES = frozenset({"deck", "hand", "monster", "spell", "graveyard", "banished", "extra"})


def _fingerprint(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _key(request: DecisionRequest) -> DecisionKey:
    data = request.data
    return (
        cast(str, data["session_id"]),
        cast(str, data["duel_id"]),
        cast(int, data["prompt_id"]),
        cast(int, data["state_version"]),
    )


@dataclass(slots=True)
class DecisionSession:
    request: DecisionRequest
    delta: StateDelta
    fingerprint: str
    decide: DecideFunction
    store: StateDatabase
    stage: dict[str, Any] | None = None
    stage_event: asyncio.Event = field(default_factory=asyncio.Event)
    query_future: asyncio.Future[dict[str, Any]] | None = None
    query_payload: dict[str, Any] | None = None
    completed_queries: dict[str, str] = field(default_factory=lambda: {})
    action_receipt_fingerprint: str | None = None
    task: asyncio.Task[None] | None = None
    failed: DecisionFailure | None = None

    def identity(self) -> dict[str, Any]:
        data = self.request.data
        return {key: data[key] for key in ("session_id", "duel_id", "prompt_id", "state_version")}

    def _envelope(self, kind: str, **payload: Any) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "kind": kind,
            **self.identity(),
            "ack_event_id": self.delta.ack_event_id,
            **payload,
        }

    def _publish(self, stage: dict[str, Any]) -> None:
        self.stage = stage
        self.stage_event.set()

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            action, reason = await self.decide(self.request, self.delta, self.ask_client)
            if time.time() * 1000 > cast(int, self.request.data["deadline_unix_ms"]):
                raise DecisionFailure("timeout", "decision deadline expired")
            action_id = secrets.token_hex(16)
            self.store.append_record(
                cast(str, self.request.data["session_id"]),
                cast(str, self.request.data["duel_id"]),
                "agent_action",
                action_id,
                {"prompt_id": self.request.data["prompt_id"], "action": action, "reason": reason},
            )
            self._publish(
                self._envelope("action", action_id=action_id, reason=reason, action=action)
            )
        except asyncio.CancelledError:
            if self.failed is None:
                self.failed = DecisionFailure("stale_prompt", "decision cancelled")
            self.stage_event.set()
            raise
        except DecisionFailure as exc:
            self.failed = exc
            self.stage_event.set()
        except Exception as exc:
            self.failed = DecisionFailure("internal_error", str(exc))
            self.stage_event.set()

    async def ask_client(self, query: dict[str, Any]) -> dict[str, Any]:
        if self.query_future is not None:
            raise DecisionFailure("invalid_query", "another client query is pending")
        kind = query.get("kind")
        if kind == "inspect_zone":
            if (
                set(query) != {"kind", "player", "zone"}
                or type(query.get("player")) is not int
                or query["player"] not in (0, 1)
                or not isinstance(query.get("zone"), str)
                or query.get("zone") not in VISIBLE_ZONES
            ):
                raise DecisionFailure("invalid_query", "invalid zone query")
        elif kind == "inspect_card":
            if set(query) != {"kind", "instance_id"} or not isinstance(
                query.get("instance_id"), str
            ):
                raise DecisionFailure("invalid_query", "invalid card query")
        else:
            raise DecisionFailure("invalid_query", "unsupported client query")
        loop = asyncio.get_running_loop()
        query_id = secrets.token_hex(16)
        self.query_future = loop.create_future()
        self.query_payload = query
        self._publish(self._envelope("query", query_id=query_id, query=query))
        try:
            result = await self.query_future
        finally:
            self.query_future = None
            self.query_payload = None
        return result

    async def wait_stage(self) -> dict[str, Any]:
        if self.action_receipt_fingerprint is not None:
            raise DecisionFailure("stale_prompt", "action has already been acknowledged")
        deadline = cast(int, self.request.data["deadline_unix_ms"])
        remaining = max(0, (deadline - int(time.time() * 1000)) / 1000)
        if self.stage is None and self.failed is None:
            try:
                await asyncio.wait_for(self.stage_event.wait(), timeout=remaining)
            except TimeoutError as exc:
                self.cancel()
                raise DecisionFailure("timeout", "decision deadline expired") from exc
        if self.failed is not None:
            raise self.failed
        if self.action_receipt_fingerprint is not None:
            raise DecisionFailure("stale_prompt", "action has already been acknowledged")
        if self.stage is None:
            raise DecisionFailure("internal_error", "decision produced no stage")
        return self.stage

    def accept_query_result(self, message: dict[str, Any]) -> None:
        if any(message.get(key) != value for key, value in self.identity().items()):
            raise DecisionFailure("stale_prompt", "client query identity mismatch")
        query_id = message.get("query_id")
        if not isinstance(query_id, str):
            raise DecisionFailure("invalid_request", "query ID must be a string")
        digest = _fingerprint(message)
        old_digest = self.completed_queries.get(query_id)
        if old_digest is not None:
            if digest != old_digest:
                raise DecisionFailure("query_conflict", "query result changed on replay")
            return
        if self.stage is None or self.stage.get("kind") != "query":
            raise DecisionFailure("query_not_pending", "no client query is pending")
        if query_id != self.stage["query_id"]:
            raise DecisionFailure("query_not_pending", "query ID does not match")
        result = message.get("result")
        if "error" in message:
            error = message["error"]
            code = cast(dict[str, Any], error).get("code") if isinstance(error, dict) else None
            if code not in ("stale_prompt", "not_visible", "unavailable"):
                code = "unavailable"
            self.failed = DecisionFailure(code, "client query failed")
            self.completed_queries[cast(str, self.stage["query_id"])] = digest
            self.cancel()
            return
        if self.query_payload is None or not isinstance(result, dict):
            raise DecisionFailure("invalid_request", "client query result is malformed")
        result = cast(dict[str, Any], result)
        if result.get("kind") != self.query_payload.get("kind"):
            raise DecisionFailure("invalid_request", "client query kind mismatch")
        snapshot = cast(dict[str, Any], self.request.data["observation"])
        zones = cast(list[dict[str, Any]], snapshot["zones"])
        if result["kind"] == "inspect_zone":
            matching = [
                zone
                for zone in zones
                if zone["player"] == self.query_payload["player"]
                and zone["name"] == self.query_payload["zone"]
            ]
            if (
                set(result) != {"kind", "zone"}
                or len(matching) != 1
                or result["zone"] != matching[0]
            ):
                raise DecisionFailure("invalid_request", "zone result differs from frozen snapshot")
        else:
            matching_cards = [
                card
                for zone in zones
                for card in zone["cards"]
                if card.get("instance_id") == self.query_payload["instance_id"]
            ]
            if (
                set(result) != {"kind", "card"}
                or len(matching_cards) != 1
                or result["card"] != matching_cards[0]
            ):
                raise DecisionFailure("invalid_request", "card result differs from frozen snapshot")
        session, duel, _, _ = _key(self.request)
        self.store.append_record(
            session,
            duel,
            "client_query",
            cast(str, self.stage["query_id"]),
            {"query": self.query_payload, "result": result},
        )
        self.completed_queries[cast(str, self.stage["query_id"])] = digest
        self.stage = None
        self.stage_event.clear()
        assert self.query_future is not None
        self.query_future.set_result(result)

    def accept_action_receipt(self, message: dict[str, Any]) -> None:
        if self.stage is None or self.stage.get("kind") != "action":
            raise DecisionFailure("action_conflict", "no action has been issued")
        if any(message.get(key) != value for key, value in self.identity().items()):
            raise DecisionFailure("stale_prompt", "action receipt identity mismatch")
        if message.get("action_id") != self.stage["action_id"]:
            raise DecisionFailure("action_conflict", "action ID does not match")
        if message.get("status") not in ("submitted", "stale_prompt", "rejected"):
            raise DecisionFailure("invalid_request", "invalid action receipt status")
        digest = _fingerprint(message)
        if self.action_receipt_fingerprint is not None:
            if digest != self.action_receipt_fingerprint:
                raise DecisionFailure("action_conflict", "action receipt changed on replay")
            return
        session, duel, _, _ = _key(self.request)
        self.store.append_record(
            session,
            duel,
            "action_receipt",
            cast(str, self.stage["action_id"]),
            message,
        )
        self.action_receipt_fingerprint = digest

    def cancel(self) -> None:
        if self.query_future is not None and not self.query_future.done():
            self.query_future.cancel()
        if self.task is not None and not self.task.done():
            self.task.cancel()


class DecisionManager:
    def __init__(self, store: StateDatabase, decide: DecideFunction) -> None:
        self.store = store
        self.decide = decide
        self._sessions: dict[DecisionKey, DecisionSession] = {}
        self._lock = asyncio.Lock()

    async def decision(self, request: DecisionRequest) -> dict[str, Any]:
        key = _key(request)
        async with self._lock:
            session = self._sessions.get(key)
            fingerprint = _fingerprint(request.data)
            if session is None:
                record_id = f"{key[2]}:{key[3]}"
                started = self.store.get_record(key[0], key[1], "decision_started", record_id)
                if started is not None:
                    previous_fingerprint = started["payload"].get("fingerprint")
                    if previous_fingerprint != fingerprint:
                        raise DecisionFailure("state_conflict", "decision replay changed")
                    raise DecisionFailure("stale_prompt", "interrupted decision cannot resume")
                for old_key, previous in list(self._sessions.items()):
                    if old_key[:2] == key[:2] and old_key != key:
                        previous.cancel()
                        del self._sessions[old_key]
                delta = self.store.apply_decision(request.data)
                self.store.append_record(
                    key[0], key[1], "decision_started", record_id,
                    {"fingerprint": fingerprint},
                )
                session = DecisionSession(request, delta, fingerprint, self.decide, self.store)
                self._sessions[key] = session
                session.start()
            elif session.fingerprint != fingerprint:
                raise DecisionFailure("state_conflict", "decision replay changed")
        return await session.wait_stage()

    async def query_result(self, message: dict[str, Any]) -> dict[str, Any]:
        key = self._message_key(message)
        session = self._sessions.get(key)
        if session is None:
            raise DecisionFailure("query_not_pending", "decision is not active")
        session.accept_query_result(message)
        return await session.wait_stage()

    def action_result(self, message: dict[str, Any]) -> dict[str, Any]:
        key = self._message_key(message)
        session = self._sessions.get(key)
        if session is None:
            raise DecisionFailure("action_conflict", "decision is not active")
        session.accept_action_receipt(message)
        return {"schema_version": 3, **session.identity(), "status": "acknowledged"}

    @staticmethod
    def _message_key(message: dict[str, Any]) -> DecisionKey:
        fields = ("session_id", "duel_id", "prompt_id", "state_version")
        if any(field not in message for field in fields):
            raise DecisionFailure("invalid_request", "missing decision identity")
        session, duel, prompt, version = (message[field] for field in fields)
        if not isinstance(session, str) or not isinstance(duel, str):
            raise DecisionFailure("invalid_request", "invalid decision identity")
        if type(prompt) is not int or type(version) is not int:
            raise DecisionFailure("invalid_request", "invalid decision identity")
        return session, duel, prompt, version
