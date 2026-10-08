"""The scenario runner checks accepted test-service events, including sync-only batches."""

from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

from agent_sdk.scenario import Scenario, ScenarioError
from agent_sdk.state_journal import StateJournal


class AcceptedEventAssertionTests(unittest.TestCase):
    def test_sync_only_reveal_is_checked_from_persisted_journal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner = runpy.run_path(str(root / "tools/agent-e2e.py"))
        scenario = Scenario(
            {
                "schema_version": 1,
                "decks": {"host": "a.ydk", "guest": "b.ydk"},
                "pregame": {
                    "host": "rock",
                    "guest": "paper",
                    "winner_chooses": "go_first",
                },
                "steps": {"host": [], "guest": []},
                "goal": {"kind": "checkpoint", "expect": {"host": {}}},
                "event_assertions": {
                    "host": [
                        {"kind": "cards_revealed", "cards": [{"card_id": "123"}]},
                        {
                            "kind": "shuffle_message_observed",
                            "player": "opponent",
                            "zone": "hand",
                        },
                    ]
                },
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            journal = StateJournal(work / "state")
            reveal = {
                "event_id": 1,
                "kind": "cards_revealed",
                "cards": [{"card_id": 123, "player": 1, "location": 2}],
            }
            envelope = {
                "schema_version": 2,
                "session_id": "client-host",
                "duel_id": "duel",
                "database_sha256": "a" * 64,
                "history_complete": True,
                "events": [reveal],
            }
            journal.apply_sync(envelope)
            decision = {
                "schema_version": 2,
                "session_id": "client-host",
                "duel_id": "duel",
                "database_sha256": "a" * 64,
                "history_complete": True,
                "state_version": 1,
                "prompt_id": 1,
                "prompt": {"kind": "idle_command", "candidates": []},
                "observation": {
                    "test_role": "host",
                    "self_player": 0,
                    "turn_player": 0,
                    "turn": 1,
                    "phase": "main_1",
                    "life_points": [8000, 8000],
                    "zones": [{"player": 1, "name": "hand", "count": 1, "cards": []}],
                    "events": [reveal],
                },
            }
            journal.apply_decision(decision)
            with self.assertRaisesRegex(ScenarioError, "event_assertions\\[1\\]"):
                runner["assert_recorded_events"](scenario, work)
            envelope["events"] = [
                {
                    "event_id": 2,
                    "kind": "shuffle_message_observed",
                    "player": 1,
                    "zone": "hand",
                }
            ]
            journal.apply_sync(envelope)
            runner["assert_recorded_events"](scenario, work)


if __name__ == "__main__":
    unittest.main()
