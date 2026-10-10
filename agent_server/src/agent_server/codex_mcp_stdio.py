"""Minimal MCP stdio child: JSON-RPC framing and authenticated parent forwarding."""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any, cast

from agent_server.codex_mcp_bridge import MAX_MESSAGE_BYTES, TOOL_SCHEMAS


def _forward(name: str, arguments: dict[str, Any]) -> Any:
    path = os.environ["YGOPRO_MCP_SOCKET"]
    token = os.environ["YGOPRO_MCP_TOKEN"]
    request = (
        json.dumps(
            {"token": token, "name": name, "arguments": arguments}, ensure_ascii=False
        ).encode()
        + b"\n"
    )
    if len(request) > MAX_MESSAGE_BYTES:
        raise ValueError("tool request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(30)
        conn.connect(path)
        conn.sendall(request)
        with conn.makefile("rb") as stream:
            line = stream.readline(MAX_MESSAGE_BYTES + 1)
    if not line or len(line) > MAX_MESSAGE_BYTES:
        raise RuntimeError("MCP bridge returned no valid response")
    decoded: object = json.loads(line)
    if not isinstance(decoded, dict):
        raise RuntimeError("MCP bridge returned an invalid response")
    reply = cast(dict[str, Any], decoded)
    if not reply.get("ok"):
        raise RuntimeError(str(reply.get("error", "tool failed")))
    return reply["result"]


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        params: object = message.get("params", {})
        version = (
            cast(dict[str, Any], params).get("protocolVersion", "2025-03-26")
            if isinstance(params, dict)
            else "2025-03-26"
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ygopro-duel", "version": "1.0.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": _description(name),
                        "inputSchema": schema,
                    }
                    for name, schema in TOOL_SCHEMAS.items()
                ]
            },
        }
    if method == "tools/call":
        params: object = message.get("params", {})
        try:
            if not isinstance(params, dict):
                raise ValueError("invalid call parameters")
            typed_params = cast(dict[str, Any], params)
            name = typed_params.get("name")
            arguments: object = typed_params.get("arguments", {})
            if not isinstance(name, str) or name not in TOOL_SCHEMAS:
                raise ValueError("unknown tool")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            typed_arguments = cast(dict[str, Any], arguments)
            result = _forward(name, typed_arguments)
            content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": content}}
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "method not found"},
    }


def _description(name: str) -> str:
    descriptions = {
        "rulebook_index": "列出可读取的 OCG 规则书章节。",
        "rulebook_section": "读取指定 OCG 规则章节。",
        "card_by_id": "按卡片 ID 查询公开卡片资料。",
        "cards_by_ids": "批量按不同卡片 ID 查询公开卡片资料。",
        "search_cards": "按关键词搜索公开卡片资料，返回 ID。",
        "own_decklist": "读取我方已提交主卡组与额外卡组目录。",
        "current_state": "读取本方视角完整已确认场面快照。",
        "zone_state": "读取一个已确认区域，隐藏卡身份仍保持隐藏。",
        "card_state": "按当前场面位置键读取卡片可见状态。",
        "event_history": "分页读取本方可见的已确认事件历史。",
        "calculate": "确定性十进制加减乘除或大小比较；仅用于数字计算。",
    }
    return descriptions[name]


def main() -> None:
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_MESSAGE_BYTES:
            continue
        try:
            decoded: object = json.loads(raw)
            if not isinstance(decoded, dict):
                continue
            message = cast(dict[str, Any], decoded)
            response = _handle(message)
        except (ValueError, TypeError):
            continue
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
