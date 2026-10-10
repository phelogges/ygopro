"""Offline MCP framing, authorization and decision-lifetime checks."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from agent_server.codex_mcp_bridge import CodexMcpBridge


async def _exchange(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    message: dict[str, Any],
) -> dict[str, Any]:
    writer.write((json.dumps(message) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5)
    return cast(dict[str, Any], json.loads(line))


def test_bridge_rejects_unauthorized_and_stale_calls() -> None:
    async def run() -> None:
        bridge = CodexMcpBridge()
        await bridge.start()
        config = bridge.mcp_config()
        path = config["env"]["YGOPRO_MCP_SOCKET"]
        token = config["env"]["YGOPRO_MCP_TOKEN"]
        reader, writer = await asyncio.open_unix_connection(path)
        try:
            response = await _exchange(
                reader,
                writer,
                {"token": "wrong", "name": "calculate", "arguments": {}},
            )
            assert response["ok"] is False
            response = await _exchange(
                reader,
                writer,
                {"token": token, "name": "calculate", "arguments": {}},
            )
            assert response["ok"] is False
            assert "no active decision" in response["error"]

            records: list[str] = []

            def record_tool(name: str, args: dict[str, Any]) -> None:
                records.append(name)

            deps = SimpleNamespace(
                tool=record_tool,
                client_tool=record_tool,
                check_deadline=lambda: None,
                identity=("s", "d", 1),
                delta=SimpleNamespace(ack_event_id=2),
            )

            def current_note(
                _session: str,
                _duel: str,
                _ack: int,
                player: int,
                zone: str,
                sequence: int | None = None,
            ) -> dict[str, Any]:
                return {"status": "unwritten", "player": player, "zone": zone, "sequence": sequence}

            def write_note(
                _session: str,
                _duel: str,
                _version: int,
                _ack: int,
                player: int,
                zone: str,
                note: str,
                _evidence: list[int],
                sequence: int | None = None,
            ) -> dict[str, Any]:
                return {
                    "status": "agent_inference",
                    "player": player,
                    "zone": zone,
                    "sequence": sequence,
                    "note": note,
                }

            notes = SimpleNamespace(current=current_note, write=write_note)
            bridge.activate(cast(Any, deps), cast(Any, None), cast(Any, notes))
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "calculate",
                    "arguments": {"operation": "subtract", "left": 8000, "right": 2700},
                },
            )
            assert response == {"ok": True, "result": {"result": "5300"}}
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "write_zone_note",
                    "arguments": {
                        "player": 1,
                        "zone": "spell",
                        "note": "序号3曾展示原罪宝－蛇眼",
                        "evidence_event_ids": [1, 2],
                    },
                },
            )
            assert response["result"]["zone"] == "spell"
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "read_zone_note",
                    "arguments": {"player": 1, "zone": "spell"},
                },
            )
            assert response["result"]["zone"] == "spell"
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "write_zone_note",
                    "arguments": {
                        "player": 1,
                        "zone": "main_monster",
                        "sequence": 0,
                        "note": "序号0曾是死亡骆驼",
                        "evidence_event_ids": [1, 2],
                    },
                },
            )
            assert response["result"]["sequence"] == 0
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "read_zone_note",
                    "arguments": {"player": 1, "zone": "main_monster", "sequence": 0},
                },
            )
            assert response["result"]["sequence"] == 0
            assert records == [
                "calculate",
                "write_zone_note",
                "read_zone_note",
                "write_zone_note",
                "read_zone_note",
            ]
            bridge.deactivate()
            response = await _exchange(
                reader,
                writer,
                {
                    "token": token,
                    "name": "calculate",
                    "arguments": {"operation": "add", "left": 1, "right": 2},
                },
            )
            assert response["ok"] is False
            assert records == [
                "calculate",
                "write_zone_note",
                "read_zone_note",
                "write_zone_note",
                "read_zone_note",
            ]
        finally:
            writer.close()
            await writer.wait_closed()
            await bridge.close()
            assert not Path(path).exists()

    asyncio.run(run())


def test_bridge_batch_lookup_records_shared_metrics() -> None:
    async def run() -> None:
        bridge = CodexMcpBridge()
        await bridge.start()
        config = bridge.mcp_config()
        reader, writer = await asyncio.open_unix_connection(config["env"]["YGOPRO_MCP_SOCKET"])
        attempts: list[dict[str, Any]] = []
        metrics: list[tuple[str, dict[str, Any]]] = []

        def record_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
            record: dict[str, Any] = {"name": name, "args": args}
            attempts.append(record)
            return record

        def cards_by_ids(ids: list[int]) -> list[dict[str, Any]]:
            return [{"id": ids[0], "name": "test"}]

        def emit_metric(name: str, payload: dict[str, Any]) -> None:
            metrics.append((name, payload))

        deps = SimpleNamespace(
            tool=record_tool,
            check_deadline=lambda: None,
            settings=SimpleNamespace(limits=SimpleNamespace(card_lookup_batch_size=12)),
            skills=SimpleNamespace(cards_by_ids=cards_by_ids),
            emit_tool_metric=emit_metric,
        )
        bridge.activate(cast(Any, deps), cast(Any, None), cast(Any, None))
        try:
            response = await _exchange(
                reader,
                writer,
                {
                    "token": config["env"]["YGOPRO_MCP_TOKEN"],
                    "name": "cards_by_ids",
                    "arguments": {"card_ids": [2326738]},
                },
            )
            assert response["ok"] is True
            assert response["result"][0]["id"] == 2326738
            assert attempts[0]["distinct_card_ids"] == 1
            assert attempts[0]["result_bytes"] > 0
            assert metrics[0][0] == "card_batch_lookup"
        finally:
            writer.close()
            await writer.wait_closed()
            await bridge.close()

    asyncio.run(run())


def test_mcp_stdio_round_trip() -> None:
    async def run() -> None:
        bridge = CodexMcpBridge()
        await bridge.start()
        config = bridge.mcp_config()

        def record_tool(name: str, args: dict[str, Any]) -> None:
            pass

        deps = SimpleNamespace(
            tool=record_tool,
            client_tool=record_tool,
            check_deadline=lambda: None,
            identity=("s", "d", 1),
        )
        bridge.activate(cast(Any, deps), cast(Any, None), cast(Any, None))
        env = {**os.environ, **config["env"]}
        process = await asyncio.create_subprocess_exec(
            config["command"],
            *config["args"],
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        child_stdin = process.stdin
        child_stdout = process.stdout
        assert child_stdin is not None
        assert child_stdout is not None

        async def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            child_stdin.write((json.dumps(payload) + "\n").encode())
            await child_stdin.drain()
            line = await asyncio.wait_for(child_stdout.readline(), timeout=5)
            return cast(dict[str, Any], json.loads(line))

        try:
            response = await rpc("initialize", {"protocolVersion": "2025-03-26"})
            assert response["result"]["capabilities"] == {"tools": {}}
            response = await rpc("tools/list")
            assert {tool["name"] for tool in response["result"]["tools"]} >= {
                "current_state",
                "client_inspect_zone",
                "calculate",
            }
            response = await rpc(
                "tools/call",
                {
                    "name": "calculate",
                    "arguments": {"operation": "compare", "left": 3000, "right": 2500},
                },
            )
            assert json.loads(response["result"]["content"][0]["text"]) == {"result": "1"}
            bridge.deactivate()
            response = await rpc(
                "tools/call",
                {"name": "calculate", "arguments": {"operation": "add", "left": 1, "right": 1}},
            )
            assert response["result"]["isError"] is True
        finally:
            child_stdin.close()
            await process.wait()
            await bridge.close()

    asyncio.run(run())
