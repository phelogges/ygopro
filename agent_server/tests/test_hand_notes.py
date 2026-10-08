"""Model-authored hand notes remain separate from visible field facts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_sdk.contract import parse_request
from agent_sdk.state import StateError
from test_decision_session import request

from agent_server.hand_notes import HandNotes
from agent_server.storage import StateDatabase


class HandNoteTests(unittest.TestCase):
    def test_reveal_note_revision_and_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as store:
                first = request()
                first["observation"]["events"] = [
                    {
                        "event_id": 1,
                        "kind": "cards_revealed",
                        "message_type": 31,
                        "cards": [
                            {"player": 1, "location": 2, "card_id": 5318639},
                            {"player": 1, "location": 2, "card_id": 27755794},
                        ],
                    },
                    {
                        "event_id": 2,
                        "kind": "shuffle_message_observed",
                        "message_type": 33,
                        "player": 1,
                        "zone": "hand",
                    },
                ]
                delta = store.apply_decision(parse_request(first).data)
                notes = HandNotes(store)
                self.assertEqual(
                    notes.current("client-a", "duel-1", delta.ack_event_id)["status"], "unwritten"
                )
                written = notes.write(
                    "client-a",
                    "duel-1",
                    1,
                    delta.ack_event_id,
                    1,
                    "hand",
                    "对手展示了旋风和绚岚之米克拉，洗手后位置未知。",
                    [1, 2],
                )
                self.assertFalse(written["newer_events_exist"])
                self.assertEqual(store.get_state("client-a", "duel-1", 1)["zones"][1]["cards"], [])

                second = request()
                second["prompt_id"] = 2
                second["state_version"] = 2
                second["observation"]["events"] = [
                    {
                        "event_id": 3,
                        "kind": "card_moved",
                        "message_type": 50,
                        "from_player": 1,
                        "from_location": 2,
                        "to_player": 1,
                        "to_location": 16,
                        "reason_flags": 0,
                    }
                ]
                delta2 = store.apply_decision(parse_request(second).data)
                self.assertTrue(
                    notes.current("client-a", "duel-1", delta2.ack_event_id)["newer_events_exist"]
                )
                revised = notes.write(
                    "client-a",
                    "duel-1",
                    2,
                    delta2.ack_event_id,
                    1,
                    "hand",
                    "一张手牌离开；无法断定此前展示的两种卡是否仍在手牌。",
                    [1, 3],
                )
                self.assertNotEqual(written["revision_id"], revised["revision_id"])
                self.assertEqual(
                    len(store.get_records("client-a", "duel-1", kind="hand_note_revision")), 2
                )
                self.assertEqual(notes.current("client-b", "duel-1", 3)["status"], "unwritten")

            with StateDatabase(path) as restarted:
                self.assertEqual(
                    HandNotes(restarted).current("client-a", "duel-1", 3)["note"],
                    "一张手牌离开；无法断定此前展示的两种卡是否仍在手牌。",
                )

    def test_rejects_missing_evidence_and_other_zone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as store:
                body = request()
                body["observation"]["events"] = [
                    {"event_id": 1, "kind": "phase_changed", "message_type": 41, "phase": "main_1"}
                ]
                delta = store.apply_decision(parse_request(body).data)
                notes = HandNotes(store)
                with self.assertRaises(StateError):
                    notes.write(
                        "client-a", "duel-1", 1, delta.ack_event_id, 1, "spell", "猜测", [1]
                    )
                with self.assertRaises(StateError):
                    notes.write("client-a", "duel-1", 1, delta.ack_event_id, 1, "hand", "猜测", [2])
                self.assertEqual(notes.current("client-a", "duel-1", 1)["status"], "unwritten")
