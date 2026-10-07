"""Authenticated local HTTP v3 service and read-only human view."""

import hashlib
import hmac
import json
import secrets
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


VIEW_HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>YGOPro Agent 对局视图</title><style>
body{font:15px system-ui;margin:2rem;max-width:1100px;background:#141923;color:#edf1fa}
button,select,input{font:inherit;padding:.45rem;margin:.3rem;background:#293449;
color:white;border:1px solid #71819d}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#202a3a;padding:1rem;border-radius:.4rem}
section{margin:1.4rem 0}small{color:#b6c5d8}
</style><h1>Agent 对局视图</h1>
<p>只显示此服务进程的单方视角。状态为已确认快照，事件可更新得更晚。</p>
<label>只读令牌 <input id="token" type="password"></label><button id="load">加载对局</button>
<section><label>对局 <select id="duels"></select></label>
<button id="refresh">刷新</button></section>
<section><h2>状态与时间线</h2><small id="meta"></small><pre id="state"></pre></section>
<section><h2>最近事件</h2><pre id="events"></pre></section>
<section><h2>最近决策与回执</h2><pre id="records"></pre></section>
<script>
const token=document.getElementById('token'), duels=document.getElementById('duels');
token.value=sessionStorage.getItem('agent-view-token')||'';
async function get(path){const r=await fetch(path,{headers:{Authorization:'Bearer '+token.value}});
if(!r.ok)throw Error((await r.json()).error?.message||r.status);return r.json()}
function pretty(x){return JSON.stringify(x,null,2)}
async function load(){sessionStorage.setItem('agent-view-token',token.value);
const list=await get('/v3/view/duels');duels.innerHTML='';
for(const item of list.duels){const option=document.createElement('option');
option.value=JSON.stringify([item.session_id,item.duel_id]);
option.textContent=item.duel_id+' · 状态 '+item.state_version;duels.append(option)}await refresh()}
async function refresh(){if(!duels.value)return;const [s,d]=JSON.parse(duels.value);
const q='session_id='+encodeURIComponent(s)+'&duel_id='+encodeURIComponent(d);
const [state,events,records]=await Promise.all([
get('/v3/view/state?'+q),get('/v3/view/events?'+q+'&limit=100'),
get('/v3/view/records?'+q+'&limit=100')]);
document.getElementById('meta').textContent='快照版本 '+state.state_version+
'；已确认事件 '+state.ack_event_id+'。客户端提交的动作不代表游戏服务端已执行。';
document.getElementById('state').textContent=pretty(state.observation);
document.getElementById('events').textContent=pretty(events.events);
document.getElementById('records').textContent=pretty(records.records)}
document.getElementById('load').onclick=()=>load().catch(e=>alert(e));
document.getElementById('refresh').onclick=()=>refresh().catch(e=>alert(e));
</script></html>"""


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
    ) -> None:
        self.settings = settings
        self.store = store
        self.skills = skills
        self.manager = DecisionManager(store, decide)
        self.profile = profile
        self.nonce = nonce
        self.client_token = client_token
        self.viewer_token = viewer_token

    def app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY)
        routes: list[tuple[str, str, Callable[..., Any]]] = [
            ("GET", "/v3/ready", self.ready),
            ("POST", "/v3/decision", self.decision),
            ("POST", "/v3/query-result", self.query_result),
            ("POST", "/v3/action-result", self.action_result),
            ("POST", "/v3/sync", self.sync),
            ("POST", "/v3/status", self.status),
            ("GET", "/v3/view/duels", self.view_duels),
            ("GET", "/v3/view/state", self.view_state),
            ("GET", "/v3/view/events", self.view_events),
            ("GET", "/v3/view/deltas", self.view_deltas),
            ("GET", "/v3/view/records", self.view_records),
        ]
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)
        app.router.add_get("/view", self.view_page)
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

    async def view_page(self, _request: web.Request) -> web.Response:
        return web.Response(text=VIEW_HTML, content_type="text/html", charset="utf-8")

    async def view_duels(self, request: web.Request) -> web.Response:
        self._auth(request, viewer=True)
        try:
            return self._response({"schema_version": 3, "duels": self.store.list_duels()})
        except Exception as exc:
            return self.error(exc)

    @staticmethod
    def _view_identity(request: web.Request) -> tuple[str, str]:
        return _identity(dict(request.query))

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
            return self._response(
                {
                    "schema_version": 3,
                    "records": self.store.get_records(session, duel, after_id=after, limit=limit),
                }
            )
        except Exception as exc:
            return self.error(exc)


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
