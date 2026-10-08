"""SQLite durability and perspective isolation for the Agent service."""

from __future__ import annotations

import copy
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, cast

from agent_sdk.state import StateError

from agent_server.storage import StateDatabase


def _sync(event_id: int, *, session: str = "client-a") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "session_id": session,
        "duel_id": "duel-1",
        "database_sha256": "a" * 64,
        "history_complete": True,
        "events": [{"event_id": event_id, "kind": "observed"}],
    }


def _decision(
    version: int, events: list[dict[str, Any]] | None = None, *, session: str = "client-a"
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "session_id": session,
        "duel_id": "duel-1",
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
            "zones": [
                {"player": 0, "name": "hand", "count": 0, "cards": []},
                {"player": 1, "name": "hand", "count": 1, "cards": []},
            ],
            "events": events or [],
        },
    }


class StateDatabaseTests(unittest.TestCase):
    def test_read_only_view_refreshes_after_external_writer_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as writer:
                writer.apply_decision(_decision(1))
                with StateDatabase(path, read_only=True) as viewer:
                    self.assertEqual(viewer.get_status("client-a", "duel-1")["state_version"], 1)
                    writer.apply_decision(_decision(2))
                    self.assertEqual(viewer.get_status("client-a", "duel-1")["state_version"], 2)
                    self.assertEqual(viewer.get_state("client-a", "duel-1", 2)["turn"], 2)

    def test_sync_decision_and_restart_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path, checkpoint_interval=2) as first:
                self.assertEqual(first.apply_sync(_sync(1)), 1)
                delta = first.apply_decision(_decision(1))
                self.assertEqual(delta.ack_event_id, 1)
                self.assertIsInstance(first.last_observation_unix_ms("client-a", "duel-1"), int)
                self.assertEqual(delta.events, ({"event_id": 1, "kind": "observed"},))
                self.assertEqual(first.apply_sync(_sync(2)), 2)
                self.assertEqual(
                    first.get_status("client-a", "duel-1"), {"state_version": 1, "ack_event_id": 2}
                )
            with StateDatabase(path, checkpoint_interval=2) as second:
                self.assertEqual(
                    second.get_status("client-a", "duel-1"), {"state_version": 1, "ack_event_id": 2}
                )
                self.assertEqual(second.get_state("client-a", "duel-1", 1)["turn"], 1)
                self.assertEqual(
                    second.get_events("client-a", "duel-1", state_version=1),
                    ({"event_id": 1, "kind": "observed"},),
                )
                self.assertEqual(second.apply_decision(_decision(1)), delta)
                self.assertEqual(
                    second.apply_decision(_decision(2)).events,
                    ({"event_id": 2, "kind": "observed"},),
                )
            with StateDatabase(path) as third:
                self.assertEqual(
                    third.get_status("client-a", "duel-1"), {"state_version": 2, "ack_event_id": 2}
                )

    def test_duplicate_requests_do_not_append_and_conflicts_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                request = _decision(1, [{"event_id": 1, "kind": "observed"}])
                expected = storage.apply_decision(request)
                self.assertEqual(storage.apply_decision(request), expected)
                self.assertEqual(storage.apply_sync(_sync(1)), 1)
                changed = copy.deepcopy(request)
                changed["prompt_id"] = 9
                with self.assertRaises(StateError) as conflict:
                    storage.apply_decision(changed)
                self.assertEqual(conflict.exception.code, "state_conflict")
                changed_event = _sync(1)
                changed_event["events"][0]["kind"] = "other"
                with self.assertRaises(StateError) as conflict:
                    storage.apply_sync(changed_event)
                self.assertEqual(conflict.exception.code, "event_conflict")
            with sqlite3.connect(path) as connection:
                count = connection.execute("SELECT count(*) FROM operations").fetchone()[0]
                self.assertEqual(count, 1)

    def test_failed_commit_does_not_publish_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                storage.apply_sync(_sync(1))
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "CREATE TRIGGER reject_new BEFORE INSERT ON operations "
                        "BEGIN SELECT RAISE(ABORT, 'disk failure'); END"
                    )
                with self.assertRaises(StateError) as error:
                    storage.apply_sync(_sync(2))
                self.assertEqual(error.exception.code, "storage_error")
                self.assertEqual(
                    storage.get_status("client-a", "duel-1"),
                    {"state_version": 0, "ack_event_id": 1},
                )
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP TRIGGER reject_new")
            with StateDatabase(path) as recovered:
                self.assertEqual(
                    recovered.get_status("client-a", "duel-1"),
                    {"state_version": 0, "ack_event_id": 1},
                )

    def test_gap_hidden_identity_and_perspectives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                with self.assertRaises(StateError) as error:
                    storage.apply_sync(_sync(2))
                self.assertEqual(error.exception.code, "event_gap")
                hidden = _decision(1)
                zone = cast(dict[str, Any], hidden["observation"])["zones"][1]
                zone["cards"] = [
                    {
                        "controller": 1,
                        "location": "hand",
                        "sequence": 0,
                        "position": "unknown",
                        "known": True,
                        "card_id": 12345678,
                    }
                ]
                with self.assertRaises(StateError) as error:
                    storage.apply_decision(hidden)
                self.assertEqual(error.exception.code, "hidden_identity")
                storage.apply_decision(_decision(1, session="client-b"))
                self.assertEqual(
                    storage.get_status("client-a", "duel-1"),
                    {"state_version": 0, "ack_event_id": 0},
                )
                self.assertEqual(
                    storage.get_status("client-b", "duel-1"),
                    {"state_version": 1, "ack_event_id": 0},
                )

    def test_auxiliary_records_are_idempotent_and_do_not_advance_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                storage.apply_decision(_decision(1))
                before = storage.get_status("client-a", "duel-1")
                first_id = storage.append_record(
                    "client-a", "duel-1", "action_receipt", "a1", {"status": "submitted"}
                )
                self.assertEqual(
                    storage.append_record(
                        "client-a", "duel-1", "action_receipt", "a1", {"status": "submitted"}
                    ),
                    first_id,
                )
                with self.assertRaises(StateError) as error:
                    storage.append_record(
                        "client-a", "duel-1", "action_receipt", "a1", {"status": "rejected"}
                    )
                self.assertEqual(error.exception.code, "record_conflict")
                self.assertEqual(storage.get_status("client-a", "duel-1"), before)
                self.assertEqual(
                    storage.get_records("client-a", "duel-1")[0]["payload"], {"status": "submitted"}
                )
                self.assertEqual(storage.get_records("client-a", "duel-1", after_id=first_id), ())
            with StateDatabase(path) as recovered:
                self.assertEqual(recovered.get_records("client-a", "duel-1")[0]["record_id"], "a1")

    def test_checkpoint_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path, checkpoint_interval=1) as storage:
                storage.apply_decision(_decision(1))
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE checkpoints SET payload=?", (b"{}",))
            with StateDatabase(path) as recovered:
                with self.assertRaises(StateError) as error:
                    recovered.get_status("client-a", "duel-1")
                self.assertEqual(error.exception.code, "invalid_storage")

    def test_deltas_can_be_paged_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path, checkpoint_interval=2) as storage:
                first = storage.apply_decision(_decision(1))
                second = storage.apply_decision(_decision(2, [{"event_id": 1, "kind": "observed"}]))
                third = storage.apply_decision(_decision(3))
                self.assertEqual(storage.get_deltas("client-a", "duel-1", limit=2), (first, second))
            with StateDatabase(path) as recovered:
                self.assertEqual(recovered.get_delta("client-a", "duel-1", 2), second)
                self.assertEqual(
                    recovered.get_deltas("client-a", "duel-1", after_version=2, limit=1), (third,)
                )
                self.assertEqual(recovered.get_deltas("client-a", "duel-1", after_version=3), ())
                with self.assertRaises(StateError) as error:
                    recovered.get_delta("client-a", "duel-1", 4)
                self.assertEqual(error.exception.code, "state_not_found")

    def test_list_duels_includes_sync_only_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                storage.apply_decision(_decision(1, session="client-a"))
                storage.apply_sync(_sync(1, session="client-b"))
                storage.add_trace("client-a", "duel-1", "", None, "duel_finished", {})
            with sqlite3.connect(path) as database:
                database.execute(
                    "UPDATE operations SET created_unix_ms=1000 WHERE session_id='client-a'"
                )
                database.execute(
                    "UPDATE operations SET created_unix_ms=2000 WHERE session_id='client-b'"
                )
                database.execute("UPDATE traces SET created_unix_ms=3000")
            with StateDatabase(path) as recovered:
                self.assertEqual(
                    recovered.list_duels(),
                    (
                        {
                            "session_id": "client-a",
                            "duel_id": "duel-1",
                            "state_version": 1,
                            "ack_event_id": 0,
                            "started_unix_ms": 1000,
                            "last_activity_unix_ms": 3000,
                            "status": "finished",
                        },
                        {
                            "session_id": "client-b",
                            "duel_id": "duel-1",
                            "state_version": 0,
                            "ack_event_id": 1,
                            "started_unix_ms": 2000,
                            "last_activity_unix_ms": 2000,
                            "status": "unconfirmed",
                        },
                    ),
                )

    def test_trace_paging_isolation_and_atomic_duel_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path, checkpoint_interval=1) as storage:
                storage.apply_decision(_decision(1, session="client-a"))
                storage.apply_decision(_decision(1, session="client-b"))
                storage.append_record("client-a", "duel-1", "model_exchange", "r1", {"ok": True})
                first = storage.add_trace("client-a", "duel-1", "t1", None, "prompt", {"p": 1})
                second = storage.add_trace(
                    "client-a", "duel-1", "t1", "r1", "model_response", {"text": "测试"}
                )
                third = storage.add_trace("client-b", "duel-1", "t1", None, "prompt", {"p": 2})
                self.assertEqual(
                    [event["id"] for event in storage.get_traces("client-a", "duel-1")],
                    [first, second],
                )
                self.assertEqual(
                    storage.get_traces("client-a", "duel-1", after_id=first, limit=1)[0]["payload"],
                    {"text": "测试"},
                )
                self.assertTrue(storage.delete_duel("client-a", "duel-1"))
                self.assertFalse(storage.delete_duel("client-a", "duel-1"))
                self.assertEqual(storage.get_traces("client-a", "duel-1"), ())
                self.assertEqual(storage.get_records("client-a", "duel-1"), ())
                self.assertEqual(storage.get_status("client-a", "duel-1")["state_version"], 0)
                self.assertEqual(storage.get_status("client-b", "duel-1")["state_version"], 1)
                self.assertTrue(storage.delete_duel("client-b", "duel-1"))
                later = storage.add_trace("client-a", "duel-2", "", None, "duel_started", {})
                self.assertGreater(later, third)
            with sqlite3.connect(path) as connection:
                for table in ("operations", "checkpoints", "records", "traces"):
                    self.assertEqual(
                        connection.execute(
                            f"SELECT count(*) FROM {table} "
                            "WHERE session_id='client-a' AND duel_id='duel-1'"
                        ).fetchone()[0],
                        0,
                    )

    def test_retention_and_size_only_prune_finished_duels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                storage.add_trace("a", "old", "t", None, "duel_finished", {"data": "x" * 100})
                storage.add_trace("a", "new", "t", None, "duel_finished", {"data": "y" * 100})
                storage.add_trace("a", "active", "t", None, "prompt", {"data": "z" * 100})
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE traces SET created_unix_ms=? WHERE duel_id='old'",
                        (int(time.time() * 1000) - 40 * 86_400_000,),
                    )
                self.assertEqual(storage.prune_finished(30, 1_000_000), 1)
                self.assertEqual(storage.get_traces("a", "old"), ())
                self.assertEqual(storage.prune_finished(30, 1), 1)
                self.assertEqual(storage.get_traces("a", "new"), ())
                self.assertEqual(len(storage.get_traces("a", "active")), 1)

    def test_restart_marks_unfinished_turn_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as storage:
                storage.add_trace("a", "duel", "1:1", None, "prompt_received", {})
                storage.add_trace("a", "duel", "2:2", None, "action_receipt", {})
            with StateDatabase(path) as storage:
                self.assertEqual(storage.mark_interrupted_turns(), 1)
                self.assertEqual(storage.mark_interrupted_turns(), 0)
                traces = storage.get_traces("a", "duel")
                self.assertEqual(traces[-1]["kind"], "decision_interrupted")
                self.assertEqual(traces[-1]["turn_id"], "1:1")

    def test_read_only_legacy_database_and_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with self.assertRaises(StateError):
                StateDatabase(path, read_only=True)
            self.assertFalse(path.exists())
            with StateDatabase(path) as storage:
                storage.apply_decision(_decision(1))
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE traces")
                connection.execute("PRAGMA user_version=1")
            with StateDatabase(path, read_only=True) as storage:
                self.assertEqual(storage.get_status("client-a", "duel-1")["state_version"], 1)
                self.assertEqual(storage.get_traces("client-a", "duel-1"), ())
                with self.assertRaises(StateError) as error:
                    storage.add_trace("client-a", "duel-1", "", None, "prompt", {})
                self.assertEqual(error.exception.code, "read_only")
                with self.assertRaises(StateError) as error:
                    storage.delete_duel("client-a", "duel-1")
                self.assertEqual(error.exception.code, "read_only")
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM operations").fetchone()[0], 1
                )


if __name__ == "__main__":
    unittest.main()
