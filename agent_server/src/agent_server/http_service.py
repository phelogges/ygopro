"""Authenticated local HTTP v3 service and read-only human view."""

import asyncio
import hashlib
import hmac
import json
import secrets
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import ContractError, parse_request
from agent_sdk.state import StateError
from aiohttp import web

from agent_server.config import ServiceSettings
from agent_server.decision_session import DecideFunction, DecisionManager
from agent_server.model_agent import DecisionFailure
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase

MAX_BODY = 1024 * 1024


def web_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "web"


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _json_body(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BODY:
        raise DecisionFailure("payload_too_large", "request body exceeds 1 MiB")
    try:
        data: Any = json.loads(
            raw,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DecisionFailure("invalid_request", "invalid JSON request") from exc
    if not isinstance(data, dict):
        raise DecisionFailure("invalid_request", "request must be a JSON object")
    stack: list[tuple[Any, int]] = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > 32:
            raise DecisionFailure("invalid_request", "JSON nesting exceeds 32 levels")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in cast(dict[str, Any], value).values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in cast(list[Any], value))
    return cast(dict[str, Any], data)


def _require_version(data: dict[str, Any]) -> None:
    if type(data.get("schema_version")) is not int or data["schema_version"] != 3:
        raise DecisionFailure("unsupported_version", "schema_version must be 3")


def _identity(data: dict[str, Any]) -> tuple[str, str]:
    session, duel = data.get("session_id"), data.get("duel_id")
    if not isinstance(session, str) or not session or not isinstance(duel, str) or not duel:
        raise DecisionFailure("invalid_request", "missing session or duel ID")
    return session, duel


class HttpService:
    def __init__(
        self,
        settings: ServiceSettings,
        store: StateDatabase,
        skills: SkillResources,
        decide: DecideFunction,
        *,
        profile: str,
        nonce: str,
        client_token: str,
        viewer_token: str,
        view_only: bool = False,
    ) -> None:
        self.settings = settings
        self.store = store
        self.skills = skills
        self.manager = DecisionManager(store, decide)
        self.profile = profile
        self.nonce = nonce
        self.client_token = client_token
        self.viewer_token = viewer_token
        self.view_only = view_only

    def app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY)
        routes: list[tuple[str, str, Callable[..., Any]]] = [
            ("GET", "/v3/view/duels", self.view_duels),
            ("GET", "/v3/view/state", self.view_state),
            ("GET", "/v3/view/events", self.view_events),
            ("GET", "/v3/view/deltas", self.view_deltas),
            ("GET", "/v3/view/records", self.view_records),
            ("GET", "/v3/view/timeline", self.view_timeline),
            ("GET", "/v3/view/stream", self.view_stream),
            ("GET", "/v3/view/cards", self.view_cards),
            ("GET", "/v3/view/export", self.view_export),
        ]
        if not self.view_only:
            routes += [
                ("GET", "/v3/ready", self.ready),
                ("POST", "/v3/decision", self.decision),
                ("POST", "/v3/query-result", self.query_result),
                ("POST", "/v3/action-result", self.action_result),
                ("POST", "/v3/sync", self.sync),
                ("POST", "/v3/status", self.status),
            ]
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)
        app.router.add_get("/view", self.view_page)
        app.router.add_get("/view/app.js", self.view_script)
        app.router.add_get("/view/style.css", self.view_style)
        return app

    def _auth(self, request: web.Request, *, viewer: bool = False) -> None:
        expected = self.viewer_token if viewer else self.client_token
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {expected}"):
            raise web.HTTPUnauthorized(
                text=json.dumps(
                    {
                        "schema_version": 3,
                        "error": {"code": "unauthorized", "message": "Bearer token required"},
                    }
                ),
                content_type="application/json",
            )

    async def _body(self, request: web.Request) -> dict[str, Any]:
        if request.content_type != "application/json":
            raise DecisionFailure("invalid_request", "Content-Type must be application/json")
        return _json_body(await request.read())

    @staticmethod
    def _response(data: dict[str, Any]) -> web.Response:
        return web.json_response(data, dumps=lambda value: json.dumps(value, ensure_ascii=False))

    @staticmethod
    def error(exc: Exception) -> web.Response:
        if isinstance(exc, DecisionFailure):
            code = exc.code
        elif isinstance(exc, StateError):
            code = exc.code
        elif isinstance(exc, ContractError):
            code = exc.code
        else:
            code = "internal_error"
        status = (
            409
            if code.endswith("conflict") or code in ("stale_state", "state_gap")
            else 408
            if code == "timeout"
            else 404
            if code == "state_not_found"
            else 413
            if code == "payload_too_large"
            else 503
            if code in ("provider_unavailable", "storage_error")
            else 422
            if code in ("invalid_intent", "unsupported_prompt", "not_visible", "unavailable")
            else 400
        )
        message = (
            str(exc) if code != "internal_error" else "Agent service could not process the request"
        )
        return web.json_response(
            {"schema_version": 3, "error": {"code": code, "message": message}}, status=status
        )

    async def ready(self, request: web.Request) -> web.Response:
        self._auth(request)
        return self._response(
            {
                "schema_version": 3,
                "nonce": self.nonce,
                "profile": self.profile,
                "port": self.settings.server.port,
                "decision_timeout_ms": self.settings.limits.decision_seconds * 1000,
            }
        )

    async def decision(self, request: web.Request) -> web.Response:
        self._auth(request)
        try:
            raw = await self._body(request)
            decision = parse_request(raw)
            _require_version(decision.data)
            if decision.data["database_sha256"] != self.skills.database_sha256:
                raise DecisionFailure("database_mismatch", "client and Agent card databases differ")
            if decision.data["deadline_unix_ms"] is None:
                raise DecisionFailure("invalid_request", "v3 deadline is required")
            return self._response(await self.manager.decision(decision))
        except Exception as exc:
            return self.error(exc)

    async def query_result(self, request: web.Request) -> web.Response:
        self._auth(request)
        try:
            message = await self._body(request)
            _require_version(message)
            return self._response(await self.manager.query_result(message))
        except Exception as exc:
            return self.error(exc)

    async def action_result(self, request: web.Request) -> web.Response:
        self._auth(request)
        try:
            message = await self._body(request)
            _require_version(message)
            return self._response(self.manager.action_result(message))
        except Exception as exc:
            return self.error(exc)

    async def sync(self, request: web.Request) -> web.Response:
        self._auth(request)
        try:
            data = await self._body(request)
            _require_version(data)
            session, duel = _identity(data)
            if data.get("database_sha256") != self.skills.database_sha256:
                raise DecisionFailure("database_mismatch", "client and Agent card databases differ")
            ack = self.store.apply_sync(data)
            events = cast(list[dict[str, Any]], data.get("events", []))
            for event in events:
                if event.get("kind") != "duel_ended":
                    continue
                event_id = event.get("event_id")
                if type(event_id) is not int or event_id > ack:
                    continue
                record_id = str(event_id)
                if self.store.get_record(session, duel, "duel_finished", record_id) is None:
                    self.store.append_record(session, duel, "duel_finished", record_id, event)
                    self.store.add_trace(
                        session,
                        duel,
                        "",
                        None,
                        "duel_finished",
                        {
                            "event_id": event_id,
                            "winner": event.get("winner"),
                        },
                    )
                    self.store.prune_finished(
                        self.settings.storage.retention_days, self.settings.storage.max_bytes
                    )
            return self._response(
                {"schema_version": 3, "session_id": session, "duel_id": duel, "ack_event_id": ack}
            )
        except Exception as exc:
            return self.error(exc)

    async def status(self, request: web.Request) -> web.Response:
        self._auth(request)
        try:
            data = await self._body(request)
            _require_version(data)
            session, duel = _identity(data)
            if data.get("database_sha256") != self.skills.database_sha256:
                raise DecisionFailure("database_mismatch", "client and Agent card databases differ")
            return self._response(
                {
                    "schema_version": 3,
                    "session_id": session,
                    "duel_id": duel,
                    **self.store.get_status(session, duel),
                }
            )
        except Exception as exc:
            return self.error(exc)

    async def view_page(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(
            web_root() / "index.html",
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; base-uri 'none'"
                )
            },
        )

    async def view_script(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(web_root() / "app.js")

    async def view_style(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(web_root() / "style.css")

    async def view_duels(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            return self._response({"schema_version": 3, "duels": self.store.list_duels()})
        except Exception as exc:
            return self.error(exc)

    @staticmethod
    def _view_identity(request: web.Request) -> tuple[str, str]:
        return _identity(dict(request.query))

    def _require_view_duel(self, session: str, duel: str) -> None:
        if not any(
            item["session_id"] == session and item["duel_id"] == duel
            for item in self.store.list_duels()
        ):
            raise DecisionFailure("state_not_found", "duel is unavailable")

    @staticmethod
    def _page_int(request: web.Request, name: str, default: int, maximum: int) -> int:
        raw = request.query.get(name, str(default))
        if not raw.isascii() or not raw.isdecimal():
            raise DecisionFailure("invalid_request", f"{name} must be a nonnegative integer")
        value = int(raw)
        if value > maximum:
            raise DecisionFailure("invalid_request", f"{name} exceeds permitted range")
        return value

    async def view_state(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            status = self.store.get_status(session, duel)
            if status["state_version"] == 0:
                raise DecisionFailure("state_not_found", "no confirmed snapshot")
            return self._response(
                {
                    "schema_version": 3,
                    **status,
                    "updated_unix_ms": self.store.last_observation_unix_ms(session, duel),
                    "observation": self.store.get_state(session, duel, status["state_version"]),
                }
            )
        except Exception as exc:
            return self.error(exc)

    async def view_events(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            after = self._page_int(request, "after_event_id", 0, 2**63 - 1)
            limit = self._page_int(request, "limit", 100, 1000)
            return self._response(
                {
                    "schema_version": 3,
                    "events": self.store.get_events(
                        session, duel, after_event_id=after, limit=limit
                    ),
                }
            )
        except Exception as exc:
            return self.error(exc)

    async def view_deltas(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            after = self._page_int(request, "after_version", 0, 2**63 - 1)
            limit = self._page_int(request, "limit", 100, 1000)
            return self._response(
                {
                    "schema_version": 3,
                    "deltas": [
                        asdict(item)
                        for item in self.store.get_deltas(
                            session, duel, after_version=after, limit=limit
                        )
                    ],
                }
            )
        except Exception as exc:
            return self.error(exc)

    async def view_records(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            after = self._page_int(request, "after_id", 0, 2**63 - 1)
            limit = self._page_int(request, "limit", 100, 1000)
            kind = request.query.get("kind")
            if kind is not None and kind != "hand_note_revision":
                raise DecisionFailure("invalid_request", "unsupported record kind filter")
            return self._response(
                {
                    "schema_version": 3,
                    "records": [
                        self._public_record(item)
                        for item in self.store.get_records(
                            session, duel, after_id=after, limit=limit, kind=kind
                        )
                        if item["kind"] != "model_context"
                    ],
                }
            )
        except Exception as exc:
            return self.error(exc)

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        result = dict(record)
        payload = result.get("payload")
        if isinstance(payload, dict) and result.get("kind") == "model_exchange":
            document = cast(dict[str, Any], payload)
            result["payload"] = {
                key: value for key, value in document.items() if key != "new_messages"
            }
        return result

    def _export_page(
        self, kind: str, session: str, duel: str, after: int
    ) -> tuple[dict[str, Any], ...]:
        if kind == "events":
            try:
                return self.store.get_events(session, duel, after_event_id=after, limit=1000)
            except StateError as exc:
                if exc.code == "state_not_found":
                    return ()
                raise
        if kind == "traces":
            return self.store.get_traces(session, duel, after_id=after, limit=1000)
        return self.store.get_records(session, duel, after_id=after, limit=1000)

    async def view_timeline(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            self._require_view_duel(session, duel)
            after = self._page_int(request, "after_id", 0, 2**63 - 1)
            limit = self._page_int(request, "limit", 100, 1000)
            traces = self.store.get_traces(session, duel, after_id=after, limit=limit)
            return self._response(
                {
                    "schema_version": 3,
                    "traces": traces,
                    "next_id": traces[-1]["id"] if traces else after,
                }
            )
        except Exception as exc:
            return self.error(exc)

    async def view_stream(self, request: web.Request) -> web.StreamResponse:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            self._require_view_duel(session, duel)
            after = self._page_int(request, "after_id", 0, 2**63 - 1)
            last_id = request.headers.get("Last-Event-ID")
            if last_id is not None:
                if not last_id.isascii() or not last_id.isdecimal():
                    raise DecisionFailure("invalid_request", "Last-Event-ID must be numeric")
                after = max(after, int(last_id))
        except Exception as exc:
            return self.error(exc)
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        try:
            while True:
                traces = self.store.get_traces(session, duel, after_id=after, limit=100)
                for item in traces:
                    after = int(item["id"])
                    encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    async with asyncio.timeout(5):
                        await response.write(
                            f"id: {after}\nevent: trace\ndata: {encoded}\n\n".encode()
                        )
                if not traces:
                    async with asyncio.timeout(5):
                        await response.write(b": keepalive\n\n")
                await asyncio.sleep(0.5)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError, TimeoutError):
            pass
        return response

    async def view_cards(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            raw = request.query.get("ids", "")
            parts = raw.split(",") if raw else []
            if len(parts) > 100 or any(
                not item.isascii() or not item.isdecimal() for item in parts
            ):
                raise DecisionFailure("invalid_request", "ids must be at most 100 decimal card IDs")
            ids = [int(item) for item in parts]
            if any(not 1 <= item <= 0xFFFFFFFF for item in ids):
                raise DecisionFailure("invalid_request", "card ID outside supported range")
            cards: dict[str, str] = {}
            if ids:
                placeholders = ",".join("?" for _ in ids)
                with sqlite3.connect(
                    f"{self.skills.database.resolve().as_uri()}?mode=ro", uri=True
                ) as db:
                    for card_id, name in db.execute(
                        f"SELECT id, name FROM texts WHERE id IN ({placeholders})", ids
                    ):
                        cards[str(card_id)] = str(name)
            return self._response({"schema_version": 3, "cards": cards})
        except Exception as exc:
            return self.error(exc)

    async def view_export(self, request: web.Request) -> web.StreamResponse:
        self._auth(request, viewer=True)
        try:
            session, duel = self._view_identity(request)
            self._require_view_duel(session, duel)
            status = self.store.get_status(session, duel)
            observation = (
                self.store.get_state(session, duel, status["state_version"])
                if status["state_version"]
                else None
            )
            complete = bool(self.store.get_records(session, duel, kind="duel_finished"))
        except Exception as exc:
            return self.error(exc)
        response = web.StreamResponse(
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Disposition": 'attachment; filename="duel-export.json"',
                "Cache-Control": "no-store",
            }
        )
        await response.prepare(request)
        await response.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": session,
                    "duel_id": duel,
                    "status": status,
                    "observation": observation,
                    "complete": complete,
                },
                ensure_ascii=False,
            )[:-1].encode("utf-8")
        )
        for key in ("events", "traces", "records"):
            await response.write(f',"{key}":['.encode())
            after = 0
            first = True
            while True:
                page = self._export_page(key, session, duel, after)
                if not page:
                    break
                for item in page:
                    after = int(item["event_id" if key == "events" else "id"])
                    if key == "records":
                        if item["kind"] == "model_context":
                            continue
                        item = self._public_record(item)
                    await response.write(
                        ("" if first else ",").encode()
                        + json.dumps(item, ensure_ascii=False).encode("utf-8")
                    )
                    first = False
                if len(page) < 1000:
                    break
            await response.write(b"]")
        await response.write(b"}")
        await response.write_eof()
        return response


def load_viewer_token(data_dir: Path) -> str:
    """Create a local secret for the browser's read-only API on first start."""
    path = data_dir / "viewer-token"
    if path.exists():
        token = path.read_text(encoding="ascii").strip()
        if len(token) < 32:
            raise ValueError("viewer token file is invalid")
        return token
    token = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with path.open("x", encoding="ascii") as stream:
        stream.write(token + "\n")
    path.chmod(0o600)
    return token
