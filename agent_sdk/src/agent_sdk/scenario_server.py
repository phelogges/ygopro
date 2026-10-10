"""Local HTTP decision service for a strictly scripted two-client duel."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import cast

from . import parse_request
from .contract import ContractError, Object
from .scenario import Scenario
from .test_server import (
    MAX_BODY,
    DecisionError,
    DecisionHandler,
    DecisionServer,
    _strict_object,  # pyright: ignore[reportPrivateUsage]
)


class ScenarioHandler(DecisionHandler):
    def do_POST(self) -> None:
        if self.path != "/v3/scenario-action":
            super().do_POST()
            return
        server = cast(ScenarioDecisionServer, self.server)
        if not server.token or not hmac.compare_digest(
            self.headers.get("Authorization", "").encode("utf-8"),
            ("Bearer " + server.token).encode("utf-8"),
        ):
            self._error(401, "unauthorized", "Bearer token required", 3)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            self._error(400, "invalid_request", "A single Content-Length is required", 3)
            return
        if not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 7:
            self._error(400, "invalid_request", "Invalid Content-Length", 3)
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self._error(413, "payload_too_large", "Request exceeds 1 MiB", 3)
            return
        if self.headers.get_content_type() != "application/json":
            self._error(415, "invalid_request", "Content-Type must be application/json", 3)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise DecisionError("invalid_request", "Incomplete request body", 400)
            response = server.decide_v3(_strict_object(body))
        except DecisionError as exc:
            self._error(exc.status, exc.code, str(exc), 3)
        except (ContractError, RecursionError) as exc:
            self._error(400, "invalid_request", str(exc), 3)
        except TimeoutError:
            self._error(408, "timeout", "Request body read timed out", 3)
        else:
            self._send(200, response)


class ScenarioDecisionServer(ThreadingMixIn, DecisionServer):
    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        port: int,
        cards_db: Path,
        scenario_path: Path,
        status_path: Path,
        step_delay: float = 0,
        token: str = "",
    ) -> None:
        self.scenario = Scenario.load(scenario_path)
        if not 0 <= step_delay <= 10:
            raise ValueError("step_delay must be between 0 and 10 seconds")
        self.step_delay = step_delay
        self.status_path = status_path
        self.decisions = 0
        self.last_action_unix_ms = 0
        self.failure: str | None = None
        self._lock = threading.RLock()
        self._v3_results: dict[
            tuple[str, str, str, int, int], tuple[str, threading.Event, Object | None]
        ] = {}
        super().__init__(
            "127.0.0.1", port, cards_db, token=token, state_dir=status_path.parent / "state"
        )
        self.RequestHandlerClass = ScenarioHandler
        self.write_status()

    def write_status(self) -> None:
        with self._lock:
            value: dict[str, object] = {
                "schema_version": 1,
                "status": "error" if self.failure else "running",
                "error": self.failure,
                "decisions": self.decisions,
                "last_action_unix_ms": self.last_action_unix_ms,
                "pregame_complete": self.scenario.pregame_complete,
                "first_player_role": self.scenario.first_player_role,
                "remaining_steps": self.scenario.remaining_steps(),
                "wait_for": self.scenario.status()["wait_for"],
                "ignored_decisions": self.scenario.ignored_decisions,
            }
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.status_path.with_name(self.status_path.name + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temporary, self.status_path)

    def decide(self, value: object) -> Object:
        try:
            request = parse_request(value)
            if not hmac.compare_digest(cast(str, request.data["database_sha256"]), self.digest):
                raise DecisionError("database_mismatch", "Client card database differs", 409)
            deadline = request.data["deadline_unix_ms"]
            if isinstance(deadline, int) and time.time_ns() // 1_000_000 >= deadline:
                raise DecisionError("timeout", "Decision deadline has expired", 408)
            observation = cast(Object, request.data["observation"])
            role = observation.get("test_role")
            if role not in ("host", "guest"):
                raise DecisionError("invalid_intent", "Missing test role", 400)
            response: Object | None = None
            with self._lock:
                if self.failure:
                    raise DecisionError("scenario_mismatch", self.failure, 409)
                hold = (
                    (
                        self.scenario.goal["kind"] == "checkpoint"
                        or "surrender" in self.scenario.goal
                    )
                    and self.scenario.pregame_complete
                    and not any(self.scenario.remaining_steps().values())
                )
                if not hold:
                    ignored_before = len(self.scenario.ignored_decisions)
                    response = self.scenario.decide(role, request)
                    if len(self.scenario.ignored_decisions) == ignored_before and self.step_delay:
                        time.sleep(self.step_delay)
                    if isinstance(deadline, int) and time.time_ns() // 1_000_000 >= deadline:
                        raise DecisionError("timeout", "Decision deadline has expired", 408)
                    self.decisions += 1
                    self.last_action_unix_ms = time.time_ns() // 1_000_000
                    self.write_status()
            if hold:
                # The runner evaluates the final visible snapshots and stops both
                # clients. Never hold the scenario lock while this request waits.
                while True:
                    time.sleep(0.1)
            if response is None:
                raise DecisionError("scenario_mismatch", "No scripted action", 422)
            return response
        except DecisionError as exc:
            with self._lock:
                self.failure = str(exc)
                self.write_status()
            raise
        except Exception as exc:
            with self._lock:
                self.failure = str(exc)
                self.write_status()
            raise DecisionError("scenario_mismatch", str(exc), 422) from exc

    def decide_v3(self, value: object) -> Object:
        request = parse_request(value)
        data = request.data
        if data["schema_version"] != 3:
            raise DecisionError("unsupported_version", "Expected v3 decision", 400)
        if type(data["deadline_unix_ms"]) is not int:
            raise DecisionError("invalid_request", "v3 deadline must be an integer", 400)
        observation = cast(Object, data["observation"])
        role = observation.get("test_role")
        if role not in ("host", "guest"):
            raise DecisionError("invalid_intent", "Missing test role", 400)
        key = (
            cast(str, role),
            cast(str, data["session_id"]),
            cast(str, data["duel_id"]),
            cast(int, data["prompt_id"]),
            cast(int, data["state_version"]),
        )
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        with self._lock:
            cached = self._v3_results.get(key)
            if cached is not None:
                if cached[0] != fingerprint:
                    raise DecisionError(
                        "scenario_conflict", "Decision identity reused with different content", 409
                    )
                event = cached[1]
            else:
                event = threading.Event()
                self._v3_results[key] = (fingerprint, event, None)
        if cached is not None:
            event.wait()
            with self._lock:
                cached_result = self._v3_results[key][2]
                if cached_result is None:
                    raise DecisionError("scenario_mismatch", self.failure or "Decision failed", 409)
                return cached_result
        try:
            response = self.decide(data)
            result: Object = {
                "schema_version": 3,
                "action": response["action"],
                "reason": response["reason"],
            }
            with self._lock:
                self._v3_results[key] = (fingerprint, event, result)
            return result
        finally:
            event.set()

    def decide_v2(self, value: object) -> Object:
        request = parse_request(value)
        if request.data["schema_version"] != 2:
            raise DecisionError("unsupported_version", "Expected v2 decision", 400)
        if not hmac.compare_digest(cast(str, request.data["database_sha256"]), self.digest):
            raise DecisionError("database_mismatch", "Client card database differs", 409)
        delta = self.journal.apply_decision(request.data)
        response = self.decide(request.data)
        response["ack_event_id"] = delta.ack_event_id
        return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cards-db", type=Path, required=True)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--step-delay", type=float, default=0)
    parser.add_argument("--token-env", default="YGOPRO_AGENT_E2E_SCENARIO_TOKEN")
    args = parser.parse_args()
    try:
        server = ScenarioDecisionServer(
            args.port,
            args.cards_db,
            args.scenario,
            args.status_path,
            args.step_delay,
            os.environ.get(args.token_env, ""),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    with server:
        print(f"Scenario listening on 127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
