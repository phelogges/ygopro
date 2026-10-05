"""Local HTTP decision service for a strictly scripted two-client duel."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import time
from pathlib import Path
from typing import cast

from . import parse_request
from .contract import Object
from .scenario import Scenario
from .test_server import DecisionError, DecisionServer


class ScenarioDecisionServer(DecisionServer):
    def __init__(self, port: int, cards_db: Path, scenario_path: Path, status_path: Path) -> None:
        self.scenario = Scenario.load(scenario_path)
        self.status_path = status_path
        self.decisions = 0
        self.last_action_unix_ms = 0
        self.failure: str | None = None
        super().__init__("127.0.0.1", port, cards_db)
        self.write_status()

    def write_status(self) -> None:
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
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_name(self.status_path.name + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.status_path)

    def decide(self, value: object) -> Object:
        if self.failure:
            raise DecisionError("scenario_mismatch", self.failure, 409)
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
            if (
                self.scenario.goal["kind"] == "checkpoint"
                and self.scenario.pregame_complete
                and not any(self.scenario.remaining_steps().values())
            ):
                # The runner evaluates the final visible snapshots and stops both
                # clients. Hold the next prompt so it cannot advance past the goal.
                while True:
                    time.sleep(0.1)
            response = self.scenario.decide(role, request)
            if isinstance(deadline, int) and time.time_ns() // 1_000_000 >= deadline:
                raise DecisionError("timeout", "Decision deadline has expired", 408)
            self.decisions += 1
            self.last_action_unix_ms = time.time_ns() // 1_000_000
            self.write_status()
            return response
        except DecisionError as exc:
            self.failure = str(exc)
            self.write_status()
            raise
        except Exception as exc:
            self.failure = str(exc)
            self.write_status()
            raise DecisionError("scenario_mismatch", self.failure, 422) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cards-db", type=Path, required=True)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    try:
        server = ScenarioDecisionServer(args.port, args.cards_db, args.scenario, args.status_path)
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
