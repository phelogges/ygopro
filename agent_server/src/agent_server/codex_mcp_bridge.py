"""Decision-scoped MCP tools exposed through an authenticated local socket.

The Codex MCP child never opens the duel database or client connection. It only
forwards named calls to this parent process, which binds them to the active
decision and applies the same tool budgets as the Pydantic backend.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_sdk.state import StateError

from agent_server.duel_tools import DuelTools

if TYPE_CHECKING:
    from agent_server.duel_context import DuelContext
    from agent_server.duel_tools import DecisionDeps

MAX_MESSAGE_BYTES = 1_048_576


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


INTEGER = {"type": "integer"}
STRING = {"type": "string"}
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "rulebook_index": _schema({}),
    "rulebook_section": _schema({"section": STRING}, ["section"]),
    "card_by_id": _schema({"card_id": INTEGER}, ["card_id"]),
    "cards_by_ids": _schema({"card_ids": {"type": "array", "items": INTEGER}}, ["card_ids"]),
    "search_card_descriptions": _schema(
        {"keyword": STRING, "limit": INTEGER, "offset": INTEGER}, ["keyword"]
    ),
    "search_card_names": _schema(
        {"keyword": STRING, "limit": INTEGER, "offset": INTEGER}, ["keyword"]
    ),
    "own_decklist": _schema({}),
    "current_state": _schema({}),
    "zone_state": _schema({"player": INTEGER, "zone": STRING}, ["player", "zone"]),
    "card_state": _schema({"instance_id": STRING}, ["instance_id"]),
    "event_history": _schema({"after_event_id": INTEGER, "limit": INTEGER}),
    "calculate": _schema(
        {
            "operation": {"enum": ["add", "subtract", "multiply", "divide", "compare"]},
            "left": {"type": ["integer", "number", "string"]},
            "right": {"type": ["integer", "number", "string"]},
        },
        ["operation", "left", "right"],
    ),
}


@dataclass(slots=True)
class _Active:
    deps: DecisionDeps
    tools: DuelTools


class CodexMcpBridge:
    """One bridge per agent service. Call activate for each Codex decision."""

    def __init__(self) -> None:
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._socket_path: Path | None = None
        self._server: asyncio.AbstractServer | None = None
        self._token = secrets.token_urlsafe(32)
        self._active: _Active | None = None

    async def start(self) -> None:
        if self._server is not None:
            return
        if sys.platform == "win32":
            raise NotImplementedError("Windows local MCP IPC is pending Windows validation")
        self._directory = tempfile.TemporaryDirectory(prefix="ygopro-mcp-")
        os.chmod(self._directory.name, 0o700)
        self._socket_path = Path(self._directory.name) / "bridge.sock"
        self._server = await asyncio.start_unix_server(
            self._serve, path=str(self._socket_path), limit=MAX_MESSAGE_BYTES + 1
        )
        os.chmod(self._socket_path, 0o600)

    async def close(self) -> None:
        self._active = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self._socket_path = None

    def activate(self, deps: DecisionDeps, duel_context: DuelContext) -> None:
        if self._server is None or self._active is not None:
            raise RuntimeError("MCP bridge is unavailable or a decision is already active")
        self._active = _Active(deps, DuelTools(duel_context))

    def deactivate(self) -> None:
        self._active = None

    def mcp_config(self) -> dict[str, Any]:
        """Return an SDK MCP server entry; merge under mcp_servers.ygopro_duel."""
        if self._socket_path is None:
            raise RuntimeError("MCP bridge has not started")
        return {
            "command": sys.executable,
            "args": (
                ["--codex-mcp-stdio"]
                if getattr(sys, "frozen", False)
                else ["-m", "agent_server.codex_mcp_stdio"]
            ),
            "env": {
                "YGOPRO_MCP_SOCKET": str(self._socket_path),
                "YGOPRO_MCP_TOKEN": self._token,
            },
        }

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                if len(line) > MAX_MESSAGE_BYTES:
                    break
                try:
                    decoded: object = json.loads(line)
                    if not isinstance(decoded, dict):
                        raise ValueError("invalid message")
                    message = cast(dict[str, Any], decoded)
                    result = await self._call(message)
                    reply = {"ok": True, "result": result}
                except (ValueError, TypeError, KeyError, StateError, RuntimeError) as exc:
                    reply = {"ok": False, "error": str(exc)}
                encoded = (json.dumps(reply, ensure_ascii=False) + "\n").encode()
                if len(encoded) > MAX_MESSAGE_BYTES:
                    encoded = b'{"ok":false,"error":"tool response is too large"}\n'
                writer.write(encoded)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _call(self, message: dict[str, Any]) -> Any:
        token = message.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            raise ValueError("MCP bridge authentication failed")
        active = self._active
        if active is None:
            raise RuntimeError("no active decision")
        active.deps.check_deadline()
        name = message.get("name")
        args: object = message.get("arguments", {})
        if not isinstance(name, str) or name not in TOOL_SCHEMAS:
            raise ValueError("unknown tool")
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be an object")
        typed_args = cast(dict[str, Any], args)
        result = await self._dispatch(active, name, typed_args)
        if self._active is not active:
            raise RuntimeError("decision changed during tool call")
        active.deps.check_deadline()
        return result

    async def _dispatch(self, active: _Active, name: str, args: dict[str, Any]) -> Any:
        deps = active.deps
        schema = TOOL_SCHEMAS[name]
        properties = cast(dict[str, dict[str, Any]], schema["properties"])
        required = cast(list[str], schema["required"])
        if set(args) - set(properties) or set(required) - set(args):
            raise ValueError("invalid tool argument names")
        for key, value in args.items():
            prop = properties[key]
            if prop.get("type") == "integer" and type(value) is not int:
                raise ValueError(f"{key} must be an integer")
            if prop.get("type") == "string" and type(value) is not str:
                raise ValueError(f"{key} must be a string")
            if prop.get("type") == "array" and (
                type(value) is not list
                or any(type(item) is not int for item in cast(list[Any], value))
            ):
                raise ValueError(f"{key} must be an integer array")
        return await active.tools.invoke(deps, name, args)
