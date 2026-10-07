"""Protocol stage and replay tests without a model endpoint."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from agent_sdk.contract import parse_request
from agent_sdk.state import StateDelta

from agent_server.decision_session import DecisionManager
from agent_server.model_agent import DecisionFailure
from agent_server.storage import StateDatabase


def request() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "session_id": "client-a",
        "duel_id": "duel-1",
        "database_sha256": "a" * 64,
        "history_complete": True,
        "state_version": 1,
        "prompt_id": 1,
        "deadline_unix_ms": int(time.time() * 1000) + 10_000,
        "prompt": {
            "kind": "idle_command",
            "description": "选择",
            "constraints": {},
            "candidates": [{"id": "c0", "kind": "end_turn", "description": "结束回合"}],
        },
        "observation": {
            "self_player": 0,
            "turn_player": 0,
            "turn": 1,
            "phase": "main_1",
            "life_points": [8000, 8000],
            "zones": [
                {"player": 0, "name": "graveyard", "count": 0, "cards": []},
                {"player": 1, "name": "hand", "count": 1, "cards": []},
            ],
            "events": [],
        },
    }


class DecisionSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_replay_and_action_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as store:
                calls = 0

                async def decide(
                    _request: Any, _delta: StateDelta, ask: Any
                ) -> tuple[dict[str, Any], str]:
                    nonlocal calls
                    calls += 1
                    result = await ask({"kind": "inspect_zone", "player": 0, "zone": "graveyard"})
                    self.assertEqual(result["zone"]["count"], 0)
                    return {"kind": "choice", "candidate_id": "c0"}, "结束回合"

                manager = DecisionManager(store, decide)
                parsed = parse_request(request())
                first = await manager.decision(parsed)
                self.assertEqual(first["kind"], "query")
                self.assertEqual(await manager.decision(parsed), first)
                response: dict[str, Any] = {
                    **{
                        key: first[key]
                        for key in (
                            "schema_version",
                            "session_id",
                            "duel_id",
                            "prompt_id",
                            "state_version",
                            "query_id",
                        )
                    },
                    "result": {
                        "kind": "inspect_zone",
                        "zone": {"player": 0, "name": "graveyard", "count": 0, "cards": []},
                    },
                }
                action = await manager.query_result(response)
                self.assertEqual(action["kind"], "action")
                self.assertEqual(await manager.query_result(response), action)
                self.assertEqual(calls, 1)
                changed: dict[str, Any] = {
                    **response,
                    "result": {"kind": "inspect_zone", "zone": {"count": 1}},
                }
                with self.assertRaises(DecisionFailure) as error:
                    await manager.query_result(changed)
                self.assertEqual(error.exception.code, "query_conflict")
                receipt = {
                    **{
                        key: action[key]
                        for key in (
                            "schema_version",
                            "session_id",
                            "duel_id",
                            "prompt_id",
                            "state_version",
                            "action_id",
                        )
                    },
                    "status": "submitted",
                }
                manager.action_result(receipt)
                manager.action_result(receipt)
                with self.assertRaises(DecisionFailure) as error:
                    await manager.decision(parsed)
                self.assertEqual(error.exception.code, "stale_prompt")
                restarted = DecisionManager(store, decide)
                with self.assertRaises(DecisionFailure) as error:
                    await restarted.decision(parsed)
                self.assertEqual(error.exception.code, "stale_prompt")
                self.assertEqual(calls, 1)
                self.assertEqual(
                    len(store.get_records("client-a", "duel-1", kind="action_receipt")), 1
                )

    async def test_client_query_failure_aborts_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as store:
                resumed = False

                async def decide(
                    _request: Any, _delta: StateDelta, ask: Any
                ) -> tuple[dict[str, Any], str]:
                    nonlocal resumed
                    await ask({"kind": "inspect_card", "instance_id": "0:16:0"})
                    resumed = True
                    return {"kind": "choice", "candidate_id": "c0"}, "invalid"

                manager = DecisionManager(store, decide)
                first = await manager.decision(parse_request(request()))
                response = {
                    **{
                        key: first[key]
                        for key in (
                            "schema_version",
                            "session_id",
                            "duel_id",
                            "prompt_id",
                            "state_version",
                            "query_id",
                        )
                    },
                    "error": {"code": "not_visible", "message": "not visible"},
                }
                with self.assertRaises(DecisionFailure) as error:
                    await manager.query_result(response)
                self.assertEqual(error.exception.code, "not_visible")
                await asyncio.sleep(0)
                self.assertFalse(resumed)


if __name__ == "__main__":
    unittest.main()
