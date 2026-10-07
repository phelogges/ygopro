"""Deterministic HTTP contract exerciser; not a competitive duel agent."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import itertools
import json
import os
import socket
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

from . import (
    ContractError,
    DecisionRequest,
    UnsupportedPrompt,
    build_response,
    parse_request,
    translate_intent,
)
from .contract import JSON, Object
from .state import StateError
from .state_journal import StateJournal

MAX_BODY = 1024 * 1024
MAX_ATTEMPTS = 8192


class DecisionError(ValueError):
    """An explicit HTTP decision failure."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def database_digest(path: Path) -> str:
    """Hash actual database bytes; never trust the client's claimed fingerprint."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _check_deadline(request: DecisionRequest) -> None:
    deadline = request.data["deadline_unix_ms"]
    if isinstance(deadline, int) and time.time_ns() // 1_000_000 >= deadline:
        raise DecisionError("timeout", "Decision deadline has expired", 408)


def _intents(request: DecisionRequest) -> Iterator[Object]:
    kind = request.prompt["kind"]
    candidates = request.candidates
    constraints = cast(Object, request.prompt["constraints"])
    if kind == "rock_paper_scissors":
        observation = cast(Object, request.data["observation"])
        preferred = "paper" if observation.get("test_role") == "guest" else "rock"
        for candidate in candidates:
            if candidate["kind"] == preferred:
                yield {"kind": "choice", "candidate_id": candidate["id"]}
        return
    if kind in ("idle_command", "battle_command"):
        # Avoid repeatedly activating reversible effects or changing positions.
        # Finite summon/set operations prepare the field, then attack and advance.
        priorities = (
            ["normal_summon", "set_monster", "set_spell_trap", "battle_phase", "end_turn"]
            if kind == "idle_command"
            else ["attack", "main_phase_2", "end_turn"]
        )
        for preferred in priorities:
            for candidate in candidates:
                if candidate["kind"] == preferred:
                    yield {"kind": "choice", "candidate_id": candidate["id"]}
        return
    if kind in ("unselect_card", "select_unselect_card"):
        # Select an available card until the engine exposes finish; never toggle
        # a selected card back out and create a deterministic selection loop.
        for preferred in ("finish", "select", "cancel"):
            for candidate in candidates:
                if candidate["kind"] == preferred:
                    yield {"kind": "select_step", "candidate_id": candidate["id"]}
        return
    if kind in ("place", "select_place", "disfield"):
        count = constraints.get("count", constraints.get("min_count"))
        if type(count) is not int or count < 0 or count > len(candidates):
            raise UnsupportedPrompt("Missing or invalid place count")
        if count == 0 and candidates:
            maximum = constraints.get("max_count", 0)
            if type(maximum) is not int:
                raise UnsupportedPrompt("Invalid optional place maximum")
            if maximum >= 1:
                count = 1
        for selected in itertools.combinations(candidates, count):
            if all({"controller", "location", "sequence"} <= c.keys() for c in selected):
                places: list[JSON] = [
                    {key: c[key] for key in ("controller", "location", "sequence")}
                    for c in selected
                ]
                yield {"kind": "select_places", "places": places}
        return
    if kind in ("counter", "select_counter"):
        remaining = constraints.get("total_count")
        if type(remaining) is not int or remaining < 0:
            raise UnsupportedPrompt("Missing or invalid counter total")
        allocations: list[JSON] = []
        for candidate in candidates:
            capacity = candidate.get("counter_capacity", candidate.get("max_count"))
            if type(capacity) is not int or capacity < 0:
                raise UnsupportedPrompt("Missing or invalid counter capacity")
            count = min(remaining, capacity)
            allocations.append({"candidate_id": candidate["id"], "count": count})
            remaining -= count
        if not remaining:
            yield {"kind": "distribute_counters", "allocations": allocations}
        return
    if kind == "announce_card":
        allowed = constraints.get("allowed_card_ids")
        if not isinstance(allowed, list):
            raise UnsupportedPrompt("Announcement requires resolved allowed_card_ids")
        for card_id in allowed:
            yield {"kind": "announce_card", "card_id": card_id}
        return
    if kind in (
        "select_card",
        "select_cards",
        "tribute",
        "sum",
        "sort",
        "announce_race",
        "announce_attribute",
    ):
        selectable = [c for c in candidates if c["kind"] not in ("cancel", "default")]
        if kind == "sort":
            yield {"kind": "select_cards", "candidate_ids": [c["id"] for c in selectable]}
            return
        minimum = constraints.get("count", constraints.get("min_count"))
        maximum = constraints.get("count", constraints.get("max_count"))
        if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum:
            raise UnsupportedPrompt("Missing or invalid selection count")
        mandatory = [c for c in selectable if c.get("mandatory") is True]
        optional = [c for c in selectable if c.get("mandatory") is not True]
        for size in range(
            max(0, minimum - len(mandatory)), min(len(optional), maximum - len(mandatory)) + 1
        ):
            for selected in itertools.combinations(optional, size):
                ids: list[JSON] = [c["id"] for c in mandatory + list(selected)]
                yield {"kind": "select_cards", "candidate_ids": ids}
        for candidate in candidates:
            if candidate["kind"] == "cancel":
                yield {"kind": "choice", "candidate_id": candidate["id"]}
        return
    # Chain pass and optional effect decline avoid gratuitous effect loops.
    ordered = sorted(candidates, key=lambda c: c["kind"] not in ("pass", "decline"))
    for candidate in ordered:
        yield {"kind": "choice", "candidate_id": candidate["id"]}


def decide(value: object, digest: str) -> Object:
    request = parse_request(value)
    if not hmac.compare_digest(cast(str, request.data["database_sha256"]), digest):
        raise DecisionError(
            "database_mismatch", "Client and test server card databases differ", 409
        )
    _check_deadline(request)
    for attempt, intent in enumerate(_intents(request)):
        if attempt >= MAX_ATTEMPTS:
            raise UnsupportedPrompt("Deterministic selection search limit exceeded")
        _check_deadline(request)
        try:
            action = translate_intent(request, intent)
        except UnsupportedPrompt:
            raise
        except ContractError:
            continue
        _check_deadline(request)
        return build_response(request, action, "确定性测试策略选择合法动作，推进当前决策。")
    raise UnsupportedPrompt("No safe deterministic action found; hand control back to the player")


class DecisionServer(HTTPServer):
    digest: str
    token: str
    journal: StateJournal

    def __init__(
        self,
        host: str,
        port: int,
        cards_db: Path,
        token: str = "",
        *,
        allow_lan: bool = False,
        state_dir: Path | None = None,
    ) -> None:
        if host != "localhost":
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError as exc:
                raise ValueError("Bind host must be localhost or an explicit IP address") from exc
        else:
            loopback = True
        if not loopback and (not allow_lan or not token):
            raise ValueError("Non-loopback binding requires --allow-lan and a bearer token")
        if any(char in token for char in "\r\n\0"):
            raise ValueError("Invalid bearer token")
        self.digest = database_digest(cards_db)
        self.token = token
        self.journal = StateJournal(state_dir or Path("out/agent-state"))
        if ":" in host:
            self.address_family = socket.AF_INET6
        super().__init__((host, port), DecisionHandler)

    def decide(self, value: object) -> Object:
        return decide(value, self.digest)

    def decide_v2(self, value: object) -> Object:
        request = parse_request(value)
        if request.data["schema_version"] != 2:
            raise DecisionError("unsupported_version", "Expected v2 decision", 400)
        if not hmac.compare_digest(cast(str, request.data["database_sha256"]), self.digest):
            raise DecisionError("database_mismatch", "Client and server card databases differ", 409)
        _check_deadline(request)
        delta = self.journal.apply_decision(request.data)
        response = decide(request.data, self.digest)
        response["ack_event_id"] = delta.ack_event_id
        return response

    def sync_v2(self, value: object) -> Object:
        data = _strict_object(value)
        if not hmac.compare_digest(str(data.get("database_sha256", "")), self.digest):
            raise DecisionError("database_mismatch", "Client and server card databases differ", 409)
        ack = self.journal.apply_sync(data)
        return {
            "schema_version": 2,
            "session_id": data["session_id"],
            "duel_id": data["duel_id"],
            "ack_event_id": ack,
        }

    def status_v2(self, value: object) -> Object:
        data = _strict_object(value)
        if data.get("schema_version") != 2:
            raise DecisionError("unsupported_version", "Expected v2 status", 400)
        if not hmac.compare_digest(str(data.get("database_sha256", "")), self.digest):
            raise DecisionError("database_mismatch", "Client and server card databases differ", 409)
        session = data.get("session_id")
        duel = data.get("duel_id")
        if not isinstance(session, str) or not session or not isinstance(duel, str) or not duel:
            raise DecisionError("invalid_request", "Missing session or duel ID", 400)
        return {
            "schema_version": 2,
            "session_id": session,
            "duel_id": duel,
            **self.journal.get_status(session, duel),
        }


def _strict_object(value: object) -> Object:
    if isinstance(value, bytes):

        def pairs(items: list[tuple[str, JSON]]) -> Object:
            result: Object = {}
            for key, item in items:
                if key in result:
                    raise DecisionError("invalid_request", f"Duplicate JSON key: {key}", 400)
                result[key] = item
            return result

        try:
            value = json.loads(value, object_pairs_hook=pairs)
        except (ValueError, UnicodeError) as exc:
            raise DecisionError("invalid_request", "Invalid JSON", 400) from exc
    if not isinstance(value, dict):
        raise DecisionError("invalid_request", "Expected JSON object", 400)
    return cast(Object, value)


class DecisionHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def _send(self, status: int, value: Object) -> None:
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > MAX_BODY:
            status = 500
            body = (
                b'{"schema_version":1,"error":{"code":"internal_error",'
                b'"message":"Response exceeds size limit"}}'
            )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _error(self, status: int, code: str, message: str, version: int = 1) -> None:
        self._send(status, {"schema_version": version, "error": {"code": code, "message": message}})

    def do_POST(self) -> None:
        if self.path not in ("/v1/decision", "/v2/decision", "/v2/sync", "/v2/status"):
            self._error(404, "invalid_intent", "Unknown endpoint")
            return
        version = 2 if self.path.startswith("/v2/") else 1
        server = cast(DecisionServer, self.server)
        if server.token and not hmac.compare_digest(
            self.headers.get("Authorization", "").encode("utf-8"),
            ("Bearer " + server.token).encode("utf-8"),
        ):
            self._error(401, "unauthorized", "Bearer token required", version)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding"):
            self._error(400, "invalid_intent", "Transfer-Encoding is unsupported", version)
            return
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            self._error(
                411, "invalid_intent", "A single numeric Content-Length is required", version
            )
            return
        if len(lengths[0]) > 7:
            self._error(413, "invalid_intent", "Request exceeds 1 MiB", version)
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self._error(413, "invalid_intent", "Request exceeds 1 MiB", version)
            return
        if self.headers.get_content_type() != "application/json":
            self._error(415, "invalid_intent", "Content-Type must be application/json", version)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise DecisionError("invalid_intent", "Incomplete request body", 400)
            if self.path == "/v2/sync":
                response = server.sync_v2(body)
            elif self.path == "/v2/status":
                response = server.status_v2(body)
            elif self.path == "/v2/decision":
                response = server.decide_v2(body)
            else:
                response = server.decide(body)
        except DecisionError as exc:
            self._error(exc.status, exc.code, str(exc), version)
        except StateError as exc:
            self._error(
                409 if exc.code.endswith(("gap", "conflict")) else 422, exc.code, str(exc), version
            )
        except UnsupportedPrompt as exc:
            self._error(422, exc.code, str(exc), version)
        except (ContractError, RecursionError) as exc:
            self._error(400, "invalid_intent", str(exc), version)
        except TimeoutError:
            self._error(408, "timeout", "Request body read timed out", version)
        except Exception:
            self._error(
                500, "internal_error", "Test server could not process this request", version
            )
        else:
            self._send(200, response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards-db", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--allow-lan", action="store_true")
    parser.add_argument("--token-env", default="YGOPRO_AGENT_TOKEN")
    parser.add_argument("--state-dir", type=Path, default=Path("out/agent-state"))
    args = parser.parse_args()
    try:
        server = DecisionServer(
            args.host,
            args.port,
            args.cards_db,
            os.environ.get(args.token_env, ""),
            allow_lan=args.allow_lan,
            state_dir=args.state_dir,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    with server:
        print(
            f"Listening on {args.host}:{server.server_port}; database_sha256={server.digest}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
