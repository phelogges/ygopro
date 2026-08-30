from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

MAX_FRAME_BYTES = 1_048_576


class FrameDecoder:
    """Incrementally decodes the agent_client 4-byte big-endian JSON frames."""

    def __init__(self, maximum_frame_bytes: int = MAX_FRAME_BYTES) -> None:
        if maximum_frame_bytes <= 0:
            raise ValueError("maximum_frame_bytes must be positive")
        self._maximum_frame_bytes = maximum_frame_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(data)
        messages: list[dict[str, Any]] = []
        while len(self._buffer) >= 4:
            size = int.from_bytes(self._buffer[:4], byteorder="big")
            if size > self._maximum_frame_bytes:
                self._buffer.clear()
                raise ValueError("frame exceeds maximum_frame_bytes")
            if len(self._buffer) < size + 4:
                break
            body = bytes(self._buffer[4 : size + 4])
            del self._buffer[: size + 4]
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("frame JSON root must be an object")
            messages.append(value)
        return messages


def encode_frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError("message exceeds maximum frame size")
    return len(body).to_bytes(4, byteorder="big") + body


def encode_frames(messages: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(encode_frame(message) for message in messages)
