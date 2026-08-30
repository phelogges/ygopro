from __future__ import annotations

import unittest

from ygopro_agent_sdk import (
    FrameDecoder,
    KnowledgeLedger,
    ProtocolError,
    ProtocolSession,
    encode_frame,
)


def request(event_id: int, revision: int, delta: dict[str, object]) -> dict[str, object]:
    return {
        "type": "decision_request",
        "protocol_version": 2,
        "session_id": "session-test",
        "duel_id": "duel-test",
        "event_id": event_id,
        "request_id": event_id,
        "state_revision": revision,
        "state_delta": delta,
        "decision": {
            "kind": "idle_command",
            "choices": [{"id": 3, "action": "activate"}],
            "card_choices": [{"index": 0, "card": {"id": 123}, "selection_sequence": 4}],
            "min": 1,
            "max": 1,
        },
    }


class ProtocolSessionTests(unittest.TestCase):
    def test_snapshot_patch_none_and_choice_reply(self) -> None:
        session = ProtocolSession()
        first = session.ingest_message(request(1, 1, {"mode": "snapshot", "data": {"lp": 8000}}))
        patch = request(
            2,
            2,
            {"mode": "json_patch", "data": [{"op": "replace", "path": "/lp", "value": 7000}]},
        )
        patch["base_state_revision"] = 1
        session.ingest_message(patch)
        third = session.ingest_message(request(3, 2, {"mode": "none"}))
        self.assertEqual(session.state_for("session-test", "duel-test")["lp"], 7000)
        self.assertEqual(third.state_revision, 2)  # type: ignore[union-attr]
        response = first.choose(3).to_dict()  # type: ignore[union-attr]
        self.assertEqual(response["action"]["choice_id"], 3)  # type: ignore[index]
        self.assertEqual(response["session_id"], "session-test")
        self.assertEqual(response["duel_id"], "duel-test")

    def test_last_decision_state_is_distinct_from_observed_event_projection(self) -> None:
        session = ProtocolSession()
        session.ingest_message(
            request(
                1,
                1,
                {
                    "mode": "snapshot",
                    "data": {"players": {"self": {"life_points": 1700}}},
                },
            )
        )
        session.ingest_message(
            {
                "type": "duel_event",
                "protocol_version": 3,
                "session_id": "session-test",
                "duel_id": "duel-test",
                "event_id": 2,
                "event": "life_points_changed",
                "player": "self",
                "before": 1700,
                "after": 0,
            }
        )
        session.ingest_message(
            {
                "type": "duel_event",
                "protocol_version": 3,
                "session_id": "session-test",
                "duel_id": "duel-test",
                "event_id": 3,
                "event": "duel_ended",
                "winner": "opponent",
                "reason": 1,
                "raw_winner": 1,
            }
        )

        last_decision = session.state_at_last_decision("session-test", "duel-test")
        self.assertEqual(last_decision["players"]["self"]["life_points"], 1700)
        self.assertEqual(session.state_for("session-test", "duel-test"), last_decision)
        self.assertEqual(
            session.observed_state_for("session-test", "duel-test"),
            {
                "life_points": {"self": 0},
                "duel_ended": {
                    "winner": "opponent",
                    "reason": 1,
                    "raw_winner": 1,
                    "event_id": 3,
                },
                "as_of_event_id": 3,
            },
        )

    def test_rejects_invalid_patch_base_and_choice(self) -> None:
        session = ProtocolSession()
        session.ingest_message(request(1, 1, {"mode": "snapshot", "data": {}}))
        invalid = request(2, 2, {"mode": "json_patch", "data": []})
        invalid["base_state_revision"] = 99
        with self.assertRaises(ProtocolError):
            session.ingest_message(invalid)
        valid = session.ingest_message(request(3, 1, {"mode": "none"}))
        with self.assertRaises(ValueError):
            valid.choose(99)  # type: ignore[union-attr]

    def test_ingests_engine_observed_duel_event(self) -> None:
        session = ProtocolSession()
        session.ingest_message(
            {
                "type": "duel_event",
                "protocol_version": 2,
                "session_id": "session-test",
                "duel_id": "duel-test",
                "event_id": 1,
                "event": "card_moved",
            }
        )
        self.assertEqual(session.events[0].kind, "card_moved")

    def test_v3_effect_candidate_is_description_metadata_not_printed_index(self) -> None:
        message = request(1, 1, {"mode": "snapshot", "data": {}})
        message["protocol_version"] = 3
        message["decision"]["selection_hint"] = {
            "raw_value": 507,
        }  # type: ignore[index]
        message["decision"]["choices"] = [  # type: ignore[index]
            {
                "id": 0,
                "action": "activate",
                "card": {"id": 13597785},
                "effect_candidate": {
                    "description_id": 217564560,
                    "description_offset": 0,
                    "description_text": "从卡组把1只怪兽加入手卡。",
                    "engine_candidate_index": 0,
                    "raw_flags": 0,
                    "operation": False,
                    "reset": False,
                    "forced": False,
                },
            }
        ]
        parsed = ProtocolSession().ingest_message(message)
        self.assertIsNotNone(parsed)
        effect = parsed.choices[0].effect_candidate  # type: ignore[union-attr]
        self.assertEqual(effect.description_offset, 0)  # type: ignore[union-attr]
        self.assertNotIn("printed_effect_index", effect.raw)  # type: ignore[union-attr]
        self.assertEqual(parsed.selection_hint["raw_value"], 507)  # type: ignore[union-attr,index]

    def test_unknown_fact_event_is_preserved_without_inventing_cause(self) -> None:
        event = {
            "type": "duel_event",
            "protocol_version": 3,
            "session_id": "session-test",
            "duel_id": "duel-test",
            "event_id": 1,
            "event": "cards_indicated",
            "cards": [],
            "future_field": 42,
        }
        session = ProtocolSession()
        session.ingest_message(event)
        self.assertEqual(session.events[0].raw["future_field"], 42)
        self.assertNotIn("cause", session.events[0].raw)


class FramingTests(unittest.TestCase):
    def test_incremental_frame_decoder(self) -> None:
        message = {"type": "hello", "protocol_version": 2}
        frame = encode_frame(message)
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(frame[:2]), [])
        self.assertEqual(decoder.feed(frame[2:]), [message])


class KnowledgeLedgerTests(unittest.TestCase):
    def test_known_draw_moves_duplicate_ids_from_deck_to_unbound_hand_counts(self) -> None:
        ledger = KnowledgeLedger()
        ledger.remember_card("self", "deck", 123, 0)
        ledger.remember_card("self", "deck", 123, 1)
        ledger.apply(
            {
                "event": "cards_drawn",
                "player": "self",
                "cards": [
                    {"id": 123, "known": True},
                    {"id": 123, "known": True},
                ],
            }
        )

        self.assertEqual(ledger.known_card_counts("self", "deck"), {})
        self.assertEqual(ledger.known_card_counts("self", "hand"), {123: 2})
        self.assertEqual(ledger._hidden_slots, {})

    def test_unknown_draw_downgrades_deck_knowledge_without_guessing_hand_id(self) -> None:
        ledger = KnowledgeLedger()
        ledger.remember_card("opponent", "deck", 123, 0)
        ledger.remember_card("opponent", "deck", 456, 1)
        ledger.apply(
            {
                "event": "cards_drawn",
                "player": "opponent",
                "cards": [{"known": False}],
            }
        )

        self.assertEqual(ledger.known_card_counts("opponent", "deck"), {})
        self.assertEqual(ledger.possible_card_counts("opponent", "deck"), {123: 1, 456: 1})
        self.assertEqual(ledger.known_card_counts("opponent", "hand"), {})

    def test_known_draw_removes_identity_from_possible_deck_knowledge(self) -> None:
        ledger = KnowledgeLedger()
        ledger.remember_card("opponent", "deck", 123, 0)
        ledger.remember_card("opponent", "deck", 456, 1)
        ledger.apply(
            {
                "event": "cards_drawn",
                "player": "opponent",
                "cards": [{"known": False}],
            }
        )
        ledger.apply(
            {
                "event": "cards_drawn",
                "player": "opponent",
                "cards": [{"id": 123, "known": True}],
            }
        )

        self.assertEqual(ledger.possible_card_counts("opponent", "deck"), {456: 1})
        self.assertEqual(ledger.known_card_counts("opponent", "hand"), {123: 1})

    def test_shuffle_forgets_slots_but_preserves_observed_identity(self) -> None:
        ledger = KnowledgeLedger()
        ledger.apply(
            {
                "event": "card_moved",
                "card": {"id": 123},
                "to": {"player": "opponent", "zone": "hand"},
            }
        )
        self.assertEqual(ledger.known_cards("opponent", "hand"), frozenset({123}))
        ledger.apply({"event": "hidden_zone_shuffled", "player": "opponent", "zone": "hand"})
        self.assertEqual(ledger.known_cards("opponent", "hand"), frozenset({123}))

        ledger.apply(
            {
                "event": "card_moved",
                "card": {"known": False},
                "from": {"player": "opponent", "zone": "hand", "slot_index": 0},
                "to": {"player": "opponent", "zone": "graveyard", "slot_index": 0},
            }
        )
        self.assertEqual(ledger.known_card_counts("opponent", "hand"), {})
        self.assertEqual(ledger.possible_card_counts("opponent", "hand"), {123: 1})

    def test_confirmed_cards_preserve_duplicate_counts_without_double_observation(self) -> None:
        ledger = KnowledgeLedger()
        event = {
            "event": "cards_confirmed",
            "cards": [
                {
                    "card": {"id": 123},
                    "location": {"player": "opponent", "zone": "hand", "slot_index": 0},
                },
                {
                    "card": {"id": 123},
                    "location": {"player": "opponent", "zone": "hand", "slot_index": 1},
                },
            ],
        }
        ledger.apply(event)
        ledger.apply(event)
        self.assertEqual(ledger.known_card_counts("opponent", "hand"), {123: 2})
        self.assertEqual(len(ledger.observations()), 2)
        self.assertEqual(ledger.observations()[0]["event"], "cards_confirmed")

    def test_confirmed_extra_deck_card_is_queryable(self) -> None:
        ledger = KnowledgeLedger()
        ledger.apply(
            {
                "event": "cards_confirmed",
                "observation_kind": "confirm_extra_top",
                "cards": [
                    {
                        "card": {"id": 456},
                        "location": {
                            "player": "opponent",
                            "zone": "extra",
                            "slot_index": 0,
                        },
                    }
                ],
            }
        )
        self.assertEqual(ledger.known_card_counts("opponent", "extra"), {456: 1})
