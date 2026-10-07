import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_sdk.state import StateError
from agent_sdk.state_journal import StateJournal


def _decision(version: int, event_id: int) -> dict[str, object]:
    return {
        "schema_version": 2,
        "session_id": "one",
        "duel_id": "duel",
        "database_sha256": "a" * 64,
        "history_complete": True,
        "state_version": version,
        "prompt_id": version,
        "prompt": {"kind": "idle_command", "candidates": []},
        "observation": {
            "self_player": 0,
            "turn_player": 0,
            "turn": version,
            "phase": "main_1",
            "life_points": [8000, 8000],
            "zones": [{"player": 0, "name": "hand", "count": 0, "cards": []}],
            "events": [{"event_id": event_id, "kind": "observed"}],
        },
    }


class StateJournalTests(unittest.TestCase):
    def test_sync_only_restart_then_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = StateJournal(directory)
            self.assertEqual(
                first.get_status("one", "duel"), {"state_version": 0, "ack_event_id": 0}
            )
            envelope: dict[str, object] = {
                "schema_version": 2,
                "session_id": "one",
                "duel_id": "duel",
                "database_sha256": "a" * 64,
                "history_complete": True,
                "events": [{"event_id": 1, "kind": "observed"}],
            }
            self.assertEqual(first.apply_sync(envelope), 1)
            second = StateJournal(directory)
            self.assertEqual(
                second.get_status("one", "duel"), {"state_version": 0, "ack_event_id": 1}
            )
            self.assertEqual(second.apply_decision(_decision(1, 1)).ack_event_id, 1)
            self.assertEqual(
                StateJournal(directory).get_status("one", "duel"),
                {"state_version": 1, "ack_event_id": 1},
            )

    def test_restart_restores_versions_events_and_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = StateJournal(directory)
            request = _decision(1, 1)
            result = first.apply_decision(request)
            files = list(Path(directory).glob("*.json"))
            self.assertEqual(len(files), 1)
            if os.name == "posix":
                self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            second = StateJournal(directory)
            self.assertEqual(second.get_state("one", "duel", 1)["turn"], 1)
            self.assertEqual(
                second.get_events("one", "duel"), ({"event_id": 1, "kind": "observed"},)
            )
            self.assertEqual(second.apply_decision(request), result)
            next_result = second.apply_decision(_decision(2, 2))
            self.assertEqual(next_result.ack_event_id, 2)
            third = StateJournal(directory)
            self.assertEqual(third.get_state("one", "duel", 2)["turn"], 2)
            self.assertEqual(
                third.get_events("one", "duel", state_version=1),
                ({"event_id": 1, "kind": "observed"},),
            )

    def test_truncated_and_tampered_checkpoint_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = StateJournal(directory)
            journal.apply_decision(_decision(1, 1))
            path = next(Path(directory).glob("*.json"))
            original = path.read_bytes()
            path.write_bytes(original[: len(original) // 2])
            with self.assertRaises(StateError) as error:
                StateJournal(directory).get_state("one", "duel", 1)
            self.assertEqual(error.exception.code, "invalid_checkpoint")
            wrapper = json.loads(original)
            wrapper["state"]["records"][0]["snapshot"]["turn"] = 100
            path.write_text(json.dumps(wrapper), encoding="utf-8")
            with self.assertRaises(StateError) as error:
                StateJournal(directory).get_state("one", "duel", 1)
            self.assertEqual(error.exception.code, "invalid_checkpoint")

    def test_write_failure_does_not_publish_new_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = StateJournal(directory)
            journal.apply_decision(_decision(1, 1))
            with patch.object(
                journal, "_save", side_effect=StateError("storage_error", "disk full")
            ):
                with self.assertRaises(StateError):
                    journal.apply_decision(_decision(2, 2))
            self.assertEqual(journal.get_state("one", "duel", 1)["turn"], 1)
            with self.assertRaises(StateError):
                journal.get_state("one", "duel", 2)


if __name__ == "__main__":
    unittest.main()
