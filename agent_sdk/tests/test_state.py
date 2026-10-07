import copy
import unittest
from typing import cast

from agent_sdk.state import StateError, StateStore


def event(event_id: int, kind: str = "observed") -> dict[str, object]:
    return {"event_id": event_id, "kind": kind}


def decision(version: int, events: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 2,
        "session_id": "client-a",
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
                {
                    "player": 0,
                    "name": "hand",
                    "count": 1,
                    "cards": [
                        {
                            "controller": 0,
                            "location": "hand",
                            "sequence": 0,
                            "known": True,
                            "card_id": 100,
                        }
                    ],
                },
                {"player": 1, "name": "hand", "count": 1, "cards": []},
            ],
            "events": events or [],
        },
    }


def sync(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "session_id": "client-a",
        "duel_id": "duel-1",
        "database_sha256": "a" * 64,
        "history_complete": True,
        "events": events,
    }


class StateTests(unittest.TestCase):
    def test_control_change_event(self) -> None:
        control: dict[str, object] = {
            "event_id": 1,
            "kind": "control_changed",
            "source": "client_control",
            "agent": False,
        }
        self.assertEqual(StateStore().apply_sync(sync([control])), 1)
        malformed = copy.deepcopy(control)
        malformed["agent"] = 0
        with self.assertRaises(StateError):
            StateStore().apply_sync(sync([malformed]))

    def test_public_graveyard_query_with_unknown_position(self) -> None:
        request = decision(1)
        observation = cast(dict[str, object], request["observation"])
        zones = cast(list[dict[str, object]], observation["zones"])
        zones.append(
            {
                "player": 0,
                "name": "graveyard",
                "count": 1,
                "cards": [
                    {
                        "controller": 0,
                        "location": "graveyard",
                        "sequence": 0,
                        "known": True,
                        "card_id": 94145021,
                        "position": "unknown",
                        "attack": 0,
                    }
                ],
            }
        )
        StateStore().apply_decision(request)

    def test_public_spell_generic_face_up_position(self) -> None:
        request = decision(1)
        observation = cast(dict[str, object], request["observation"])
        zones = cast(list[dict[str, object]], observation["zones"])
        card: dict[str, object] = {
            "controller": 0,
            "location": "spell",
            "sequence": 0,
            "known": True,
            "card_id": 55144522,
            "position": "face_up",
            "type": 2,
        }
        zones.append({"player": 0, "name": "spell", "count": 1, "cards": [card]})
        StateStore().apply_decision(request)
        card["position"] = "face_down"
        with self.assertRaises(StateError) as error:
            StateStore().apply_decision(request)
        self.assertEqual(error.exception.code, "hidden_identity")

    def test_status_and_ambiguous_zone_diffs(self) -> None:
        store = StateStore()
        self.assertEqual(
            store.get_status("client-a", "duel-1"), {"state_version": 0, "ack_event_id": 0}
        )
        first = decision(1, [event(1)])
        first_observation = cast(dict[str, object], first["observation"])
        first_zones = cast(list[dict[str, object]], first_observation["zones"])
        first_hand = first_zones[0]
        first_hand["count"] = 2
        first_hand["hidden_count"] = 0
        first_cards = cast(list[dict[str, object]], first_hand["cards"])
        first_cards.append(
            {"controller": 0, "location": "hand", "sequence": 1, "known": True, "card_id": 101}
        )
        first_zones[1]["hidden_count"] = 1
        first_zones.append(
            {
                "player": 0,
                "name": "graveyard",
                "count": 2,
                "hidden_count": 0,
                "cards": [
                    {
                        "controller": 0,
                        "location": "graveyard",
                        "sequence": 0,
                        "known": True,
                        "card_id": 200,
                    },
                    {
                        "controller": 0,
                        "location": "graveyard",
                        "sequence": 1,
                        "known": True,
                        "card_id": 200,
                    },
                ],
            }
        )
        first_zones.append(
            {
                "player": 0,
                "name": "monster",
                "count": 1,
                "hidden_count": 0,
                "cards": [
                    {
                        "controller": 0,
                        "location": "monster",
                        "sequence": 0,
                        "position": "face_up_attack",
                        "known": True,
                        "card_id": 300,
                        "attack": 1000,
                    },
                ],
            }
        )
        store.apply_decision(first)
        self.assertEqual(
            store.get_status("client-a", "duel-1"), {"state_version": 1, "ack_event_id": 1}
        )
        second = copy.deepcopy(first)
        second["state_version"] = 2
        second["prompt_id"] = 2
        second_observation = cast(dict[str, object], second["observation"])
        second_observation["events"] = [event(2)]
        second_zones = cast(list[dict[str, object]], second_observation["zones"])
        second_cards = cast(list[dict[str, object]], second_zones[0]["cards"])
        second_cards[0]["card_id"], second_cards[1]["card_id"] = 101, 100
        second_zones[1]["count"] = 2
        second_zones[1]["hidden_count"] = 2
        grave_cards = cast(list[dict[str, object]], second_zones[2]["cards"])
        grave_cards.pop()
        second_zones[2]["count"] = 1
        monster_cards = cast(list[dict[str, object]], second_zones[3]["cards"])
        monster_cards[0]["attack"] = 1500
        delta = store.apply_decision(second)
        ambiguous = {"hand", "graveyard"}
        for zone in ambiguous:
            self.assertTrue(
                any(
                    c["kind"] == "zone_contents_changed" and c["zone"] == zone
                    for c in delta.changes
                )
            )
            self.assertFalse(
                any(
                    c["kind"] in ("slot", "card_attribute") and c["zone"] == zone
                    for c in delta.changes
                )
            )
        self.assertTrue(
            any(c["kind"] == "card_attribute" and c["zone"] == "monster" for c in delta.changes)
        )
        self.assertTrue(
            any(
                c["kind"] == "zone_contents_changed" and c["player"] == 1 and c["zone"] == "hand"
                for c in delta.changes
            )
        )
        self.assertEqual(
            store.get_status("client-a", "duel-1"), {"state_version": 2, "ack_event_id": 2}
        )

    def test_hidden_count_must_match_omitted_cards(self) -> None:
        store = StateStore()
        request = decision(1)
        observation = cast(dict[str, object], request["observation"])
        zones = cast(list[dict[str, object]], observation["zones"])
        zones[1]["hidden_count"] = 0
        with self.assertRaises(StateError) as error:
            store.apply_decision(request)
        self.assertEqual(error.exception.code, "invalid_state")

    def test_snapshot_privacy_boundaries(self) -> None:
        def denied(mutator: object) -> None:
            request = decision(1)
            observation = cast(dict[str, object], request["observation"])
            zones = cast(list[dict[str, object]], observation["zones"])
            if mutator == "observation":
                observation["opponent_hand_ids"] = [999]
            elif mutator == "zone":
                zones[0]["secret_cards"] = [999]
            elif mutator == "card":
                cards = cast(list[dict[str, object]], zones[0]["cards"])
                cards[0]["secret_id"] = 999
            elif mutator == "deck":
                zones.append(
                    {
                        "player": 0,
                        "name": "deck",
                        "count": 1,
                        "cards": [
                            {
                                "controller": 0,
                                "location": "deck",
                                "sequence": 0,
                                "known": True,
                                "card_id": 999,
                            }
                        ],
                    }
                )
            elif mutator == "opponent_hand":
                zones[1]["cards"] = [
                    {"controller": 1, "location": "hand", "sequence": 0, "known": False}
                ]
            elif mutator == "grave":
                observation["graveyard_inspection_allowed"] = False
                zones.append(
                    {
                        "player": 0,
                        "name": "graveyard",
                        "count": 1,
                        "cards": [
                            {
                                "controller": 0,
                                "location": "graveyard",
                                "sequence": 0,
                                "known": True,
                                "card_id": 999,
                            }
                        ],
                    }
                )
            elif mutator == "opponent_extra":
                zones.append(
                    {
                        "player": 1,
                        "name": "extra",
                        "count": 1,
                        "cards": [
                            {
                                "controller": 1,
                                "location": "extra",
                                "sequence": 0,
                                "position": "face_down_defense",
                                "known": True,
                                "card_id": 999,
                            }
                        ],
                    }
                )
            elif mutator == "opponent_banished":
                zones.append(
                    {
                        "player": 1,
                        "name": "banished",
                        "count": 1,
                        "cards": [
                            {
                                "controller": 1,
                                "location": "banished",
                                "sequence": 0,
                                "position": "unknown",
                                "known": True,
                                "card_id": 999,
                            }
                        ],
                    }
                )
            elif mutator == "self_player":
                observation["self_player"] = 1
            with self.assertRaises(StateError):
                StateStore().apply_decision(request)

        for mutation in (
            "observation",
            "zone",
            "card",
            "deck",
            "opponent_hand",
            "grave",
            "opponent_extra",
            "opponent_banished",
            "self_player",
        ):
            with self.subTest(mutation=mutation):
                denied(mutation)

    def test_event_payload_whitelist_preserves_current_fact_types(self) -> None:
        request = decision(
            1,
            [
                {
                    "event_id": 1,
                    "kind": "card_moved",
                    "message_type": 50,
                    "from_player": 0,
                    "from_location": 2,
                    "to_player": 0,
                    "to_location": 16,
                    "reason_flags": 8,
                },
                {
                    "event_id": 2,
                    "kind": "cards_revealed",
                    "message_type": 31,
                    "cards": [{"player": 0, "location": 2, "sequence": 0, "card_id": 123}],
                },
                {
                    "event_id": 3,
                    "kind": "effect_activated",
                    "message_type": 70,
                    "controller": 0,
                    "location": 4,
                    "chain_index": 1,
                    "card_id": 123,
                    "description_id": 456,
                },
                {
                    "event_id": 4,
                    "kind": "battle_values_observed",
                    "message_type": 111,
                    "attacker_player": 0,
                    "attacker_attack": 1500,
                    "target_player": 1,
                    "target_defense": 1000,
                },
            ],
        )
        self.assertEqual(StateStore().apply_decision(request).ack_event_id, 4)
        for unsafe in ("raw", "frame_base64", "bytes", "hidden_cards"):
            changed = copy.deepcopy(request)
            observation = cast(dict[str, object], changed["observation"])
            events = cast(list[dict[str, object]], observation["events"])
            events[0][unsafe] = "AAAA"
            with self.subTest(field=unsafe), self.assertRaises(StateError):
                StateStore().apply_decision(changed)

    def test_sync_before_decision_and_diff_preserve_evidence(self) -> None:
        store = StateStore()
        self.assertEqual(store.apply_sync(sync([event(1)])), 1)
        first = store.apply_decision(decision(1, [event(1), event(2)]))
        self.assertEqual(first.ack_event_id, 2)
        self.assertEqual([e["event_id"] for e in first.events], [1, 2])
        second_request = decision(2, [event(3)])
        observation = second_request["observation"]
        assert isinstance(observation, dict)
        observation["life_points"] = [7500, 8000]
        zones = cast(list[dict[str, object]], observation["zones"])
        hand = zones[0]
        hand["count"] = 2
        cards = cast(list[dict[str, object]], hand["cards"])
        cards.append(
            {"controller": 0, "location": "hand", "sequence": 1, "known": True, "card_id": 101}
        )
        second = store.apply_decision(second_request)
        self.assertEqual([e["event_id"] for e in second.events], [3])
        self.assertTrue(any(c["kind"] == "zone_count" for c in second.changes))
        self.assertTrue(any(c["kind"] == "zone_contents_changed" for c in second.changes))
        self.assertTrue(any(c["kind"] == "scalar" for c in second.changes))
        self.assertFalse(any(c["kind"] == "move" for c in second.changes))
        self.assertEqual(
            store.get_events("client-a", "duel-1", after_event_id=1, limit=1),
            ({"event_id": 2, "kind": "observed"},),
        )

    def test_idempotence_and_atomic_conflicts(self) -> None:
        store = StateStore()
        request = decision(1, [event(1)])
        result = store.apply_decision(request)
        self.assertEqual(store.apply_decision(request), result)
        self.assertEqual(store.apply_sync(sync([event(1)])), 1)
        changed = copy.deepcopy(request)
        changed["prompt_id"] = 42
        with self.assertRaisesRegex(StateError, "different content") as error:
            store.apply_decision(changed)
        self.assertEqual(error.exception.code, "state_conflict")
        with self.assertRaisesRegex(StateError, "different content") as error:
            store.apply_sync(sync([event(1, "changed")]))
        self.assertEqual(error.exception.code, "event_conflict")
        self.assertEqual(store.get_events("client-a", "duel-1"), (event(1),))

    def test_gaps_incomplete_and_hidden_identity_fail_closed(self) -> None:
        store = StateStore()
        with self.assertRaises(StateError) as error:
            store.apply_sync(sync([event(2)]))
        self.assertEqual(error.exception.code, "event_gap")
        with self.assertRaises(StateError) as error:
            store.apply_decision(decision(2))
        self.assertEqual(error.exception.code, "state_gap")
        incomplete = decision(1)
        incomplete["history_complete"] = False
        with self.assertRaises(StateError) as error:
            store.apply_decision(incomplete)
        self.assertEqual(error.exception.code, "history_incomplete")
        hidden = decision(1)
        observation = hidden["observation"]
        assert isinstance(observation, dict)
        zones = cast(list[dict[str, object]], observation["zones"])
        opponent_hand = zones[1]
        opponent_hand["cards"] = [
            {"controller": 1, "location": "hand", "sequence": 0, "known": False, "card_id": 999}
        ]
        with self.assertRaises(StateError) as error:
            store.apply_decision(hidden)
        self.assertEqual(error.exception.code, "hidden_identity")

    def test_perspective_isolation_and_detached_reads(self) -> None:
        store = StateStore()
        store.apply_decision(decision(1))
        other = decision(1)
        other["session_id"] = "client-b"
        store.apply_decision(other)
        snapshot = store.get_state("client-a", "duel-1", 1)
        snapshot["turn"] = 99
        self.assertEqual(store.get_state("client-a", "duel-1", 1)["turn"], 1)
        self.assertEqual(store.get_state("client-b", "duel-1", 1)["turn"], 1)
        zone = store.get_zone("client-a", "duel-1", 1, 0, "hand")
        self.assertEqual(zone["count"], 1)
        with self.assertRaises(StateError):
            store.get_state("client-a", "duel-1", 2)

    def test_failed_event_batch_is_atomic_and_versioned_read_is_bounded(self) -> None:
        store = StateStore()
        store.apply_decision(decision(1, [event(1)]))
        with self.assertRaises(StateError) as error:
            store.apply_sync(sync([event(2), event(4)]))
        self.assertEqual(error.exception.code, "event_gap")
        self.assertEqual(store.get_events("client-a", "duel-1"), (event(1),))
        store.apply_sync(sync([event(2), event(3)]))
        self.assertEqual(store.get_events("client-a", "duel-1", state_version=1), (event(1),))
        self.assertEqual(
            [item["event_id"] for item in store.get_events("client-a", "duel-1")],
            [1, 2, 3],
        )


if __name__ == "__main__":
    unittest.main()
