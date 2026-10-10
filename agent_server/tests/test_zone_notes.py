"""Model-authored hidden-zone notes remain separate from visible field facts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_sdk.contract import parse_request
from agent_sdk.state import StateError
from test_decision_session import request

from agent_server.storage import StateDatabase
from agent_server.zone_notes import ZoneNotes


class ZoneNoteTests(unittest.TestCase):
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
                notes = ZoneNotes(store)
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
                    ZoneNotes(restarted).current("client-a", "duel-1", 3)["note"],
                    "一张手牌离开；无法断定此前展示的两种卡是否仍在手牌。",
                )

    def test_spell_note_uses_reveal_and_set_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as store:
                body = request()
                body["observation"]["events"] = [
                    {
                        "event_id": 1,
                        "kind": "card_set",
                        "message_type": 54,
                        "player": 1,
                        "location": 8,
                        "sequence": 3,
                    },
                    {
                        "event_id": 2,
                        "kind": "cards_revealed",
                        "message_type": 31,
                        "cards": [{"player": 1, "location": 8, "sequence": 3, "card_id": 89023486}],
                    },
                ]
                delta = store.apply_decision(parse_request(body).data)
                notes = ZoneNotes(store)
                written = notes.write(
                    "client-a",
                    "duel-1",
                    1,
                    delta.ack_event_id,
                    1,
                    "spell",
                    "对手魔陷区序号3的盖卡曾展示为原罪宝－蛇眼；离位后需复核。",
                    [1, 2],
                )
                self.assertEqual(written["zone"], "spell")
                self.assertEqual(written["evidence_event_ids"], [1, 2])
                self.assertEqual(notes.current("client-a", "duel-1", 2)["status"], "unwritten")
                self.assertEqual(
                    notes.current("client-a", "duel-1", 2, 1, "spell")["note"], written["note"]
                )
                self.assertEqual(
                    notes.current("client-b", "duel-1", 2, 1, "spell")["status"], "unwritten"
                )
                self.assertEqual(
                    len(store.get_records("client-a", "duel-1", kind="spell_note_revision")), 1
                )
            with StateDatabase(path) as restarted:
                self.assertEqual(
                    ZoneNotes(restarted).current("client-a", "duel-1", 2, 1, "spell")["note"],
                    written["note"],
                )

    def test_main_monster_notes_are_scoped_per_slot_and_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as store:
                body = request()
                body["observation"]["events"] = [
                    {
                        "event_id": 1,
                        "kind": "effect_activated",
                        "message_type": 70,
                        "controller": 1,
                        "location": 4,
                        "sequence": 0,
                        "card_id": 2326738,
                    },
                    {
                        "event_id": 2,
                        "kind": "position_changed",
                        "message_type": 53,
                        "player": 1,
                        "location": 4,
                        "sequence": 0,
                        "from_position": "face_up_attack",
                        "to_position": "face_down_defense",
                    },
                ]
                delta = store.apply_decision(parse_request(body).data)
                notes = ZoneNotes(store)
                written = notes.write(
                    "client-a",
                    "duel-1",
                    1,
                    delta.ack_event_id,
                    1,
                    "main_monster",
                    "序号0的里侧怪兽曾是死亡骆驼。",
                    [1, 2],
                    0,
                )
                self.assertEqual(written["sequence"], 0)
                self.assertEqual(written["evidence_event_ids"], [1, 2])
                self.assertEqual(
                    notes.current("client-a", "duel-1", 2, 1, "main_monster", 1)["status"],
                    "unwritten",
                )
                self.assertEqual(
                    notes.current("client-b", "duel-1", 2, 1, "main_monster", 0)["status"],
                    "unwritten",
                )
                self.assertEqual(
                    len(
                        store.get_records("client-a", "duel-1", kind="main_monster_note_revision_0")
                    ),
                    1,
                )
                with self.assertRaises(StateError):
                    notes.current("client-a", "duel-1", 2, 1, "main_monster", 5)
                with self.assertRaises(StateError):
                    notes.current("client-a", "duel-1", 2, 1, "main_monster")
                with self.assertRaises(StateError):
                    notes.current("client-a", "duel-1", 2, 1, "spell", 0)
            with StateDatabase(path) as restarted:
                self.assertEqual(
                    ZoneNotes(restarted).current("client-a", "duel-1", 2, 1, "main_monster", 0)[
                        "note"
                    ],
                    written["note"],
                )

    def test_rejects_missing_evidence_and_other_zone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as store:
                body = request()
                body["observation"]["events"] = [
                    {"event_id": 1, "kind": "phase_changed", "message_type": 41, "phase": "main_1"}
                ]
                delta = store.apply_decision(parse_request(body).data)
                notes = ZoneNotes(store)
                with self.assertRaises(StateError):
                    notes.write(
                        "client-a", "duel-1", 1, delta.ack_event_id, 0, "spell", "猜测", [1]
                    )
                with self.assertRaises(StateError):
                    notes.write("client-a", "duel-1", 1, delta.ack_event_id, 1, "deck", "猜测", [1])
                with self.assertRaises(StateError):
                    notes.write("client-a", "duel-1", 1, delta.ack_event_id, 1, "hand", "猜测", [2])
                self.assertEqual(notes.current("client-a", "duel-1", 1)["status"], "unwritten")
