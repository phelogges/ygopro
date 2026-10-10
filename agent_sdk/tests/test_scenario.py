import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from agent_sdk.scenario import Scenario, ScenarioError
from agent_sdk.scenario_server import ScenarioDecisionServer


def fixture(kind: str = "idle_command") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "s",
        "duel_id": "d",
        "prompt_id": 1,
        "database_sha256": "a" * 64,
        "deadline_unix_ms": None,
        "observation": {
            "self_player": 0,
            "turn_player": 0,
            "turn": 1,
            "phase": "main_1",
            "life_points": [8000, 8000],
            "zones": [
                {
                    "player": 0,
                    "name": "hand",
                    "count": 2,
                    "cards": [
                        {
                            "instance_id": "h0",
                            "card_id": 123,
                            "controller": 0,
                            "location": "hand",
                            "sequence": 0,
                        },
                        {
                            "instance_id": "h1",
                            "card_id": 123,
                            "controller": 0,
                            "location": "hand",
                            "sequence": 1,
                        },
                    ],
                }
            ],
            "events": [],
        },
        "prompt": {
            "kind": kind,
            "description": "选择",
            "constraints": {},
            "candidates": [
                {
                    "id": "c0",
                    "kind": "normal_summon",
                    "description": "召唤",
                    "card": {
                        "instance_id": "i0",
                        "card_id": 123,
                        "controller": 0,
                        "location": "hand",
                        "sequence": 0,
                    },
                },
                {
                    "id": "c1",
                    "kind": "normal_summon",
                    "description": "召唤",
                    "card": {
                        "instance_id": "i1",
                        "card_id": 123,
                        "controller": 0,
                        "location": "hand",
                        "sequence": 1,
                    },
                },
            ],
        },
    }


def scene() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "decks": {"host": "a.ydk", "guest": "b.ydk"},
        "pregame": {"host": "rock", "guest": "paper", "winner_chooses": "go_second"},
        "steps": {
            "host": [
                {
                    "expect": {
                        "prompt": "idle_command",
                        "turn": 1,
                        "phase": "main_1",
                        "zones": [
                            {
                                "player": "self",
                                "name": "hand",
                                "count": 2,
                                "contains": [{"card_id": "123", "count": 2}],
                            }
                        ],
                    },
                    "action": {
                        "kind": "choice",
                        "match": {
                            "kind": "normal_summon",
                            "card_id": "123",
                            "location": "hand",
                            "sequence": 1,
                        },
                    },
                }
            ],
            "guest": [],
        },
        "goal": {"kind": "checkpoint", "expect": {"host": {}, "guest": {}}},
    }


def finish_pregame(scenario: Scenario) -> None:
    for role in ("host", "guest"):
        request = fixture("rock_paper_scissors")
        request["prompt"]["candidates"] = [
            {"id": "r", "kind": "rock", "description": ""},
            {"id": "p", "kind": "paper", "description": ""},
        ]
        scenario.decide(role, request)
    request = fixture("first_player")
    request["prompt"]["candidates"] = [
        {"id": "f", "kind": "go_first", "description": ""},
        {"id": "s", "kind": "go_second", "description": ""},
    ]
    scenario.decide("guest", request)


class ScenarioTests(unittest.TestCase):
    def test_random_selection_event_asserts_each_view_without_hidden_sequence(self) -> None:
        data = scene()
        data["schema_version"] = 2
        data["scenario_kind"] = "random"
        data["random_target"] = {
            "message_type": 81,
            "expect": {"host": {"turn": 1}, "guest": {"turn": 1}},
        }
        data["event_assertions"] = {
            "host": [
                {
                    "kind": "cards_randomly_selected",
                    "count": 1,
                    "cards": [{"player": "opponent", "location": 2}],
                }
            ],
            "guest": [
                {
                    "kind": "cards_randomly_selected",
                    "count": 1,
                    "cards": [{"player": "self", "location": 2, "sequence": 3}],
                }
            ],
        }
        scenario = Scenario(data)
        scenario.assert_events(
            "host",
            [
                {
                    "kind": "cards_randomly_selected",
                    "count": 1,
                    "cards": [{"player": 1, "location": 2}],
                }
            ],
        )
        scenario.assert_events(
            "guest",
            [
                {
                    "kind": "cards_randomly_selected",
                    "count": 1,
                    "cards": [{"player": 0, "location": 2, "sequence": 3}],
                }
            ],
        )
        with self.assertRaisesRegex(ScenarioError, "event_assertions"):
            scenario.assert_events(
                "host",
                [
                    {
                        "kind": "cards_randomly_selected",
                        "count": 1,
                        "cards": [{"player": 1, "location": 2, "sequence": 3}],
                    }
                ],
            )

    def test_random_v2_accepts_untargeted_legal_result(self) -> None:
        data = scene()
        data["schema_version"] = 2
        data["scenario_kind"] = "random"
        data["random_target"] = {
            "message_type": 130,
            "coverage": [["heads"]],
            "expect": {"host": {"phase": "main_1"}, "guest": {"phase": "main_1"}},
        }
        scenario = Scenario(data)
        event = {"kind": "coin_tossed", "count": 1, "results": ["tails"]}
        key, case = scenario.match_random_case({"host": [event], "guest": [event]})
        self.assertEqual(key, '["tails"]')
        self.assertEqual(case["expect"]["host"], {"phase": "main_1"})

    def test_random_v2_requires_post_effect_checkpoint(self) -> None:
        data = scene()
        data["schema_version"] = 2
        data["scenario_kind"] = "random"
        data["random_target"] = {
            "message_type": 131,
            "expect": {"host": {"turn": 1}, "guest": {"turn": 1}},
        }
        data["goal"] = {"kind": "duel_end", "winner": "any"}
        with self.assertRaisesRegex(ScenarioError, "post-effect checkpoint"):
            Scenario(data)

    def test_random_selection_rejects_identity_coverage(self) -> None:
        data = scene()
        data["schema_version"] = 2
        data["scenario_kind"] = "random"
        data["random_target"] = {
            "message_type": 81,
            "coverage": [[1]],
            "expect": {"host": {"turn": 1}, "guest": {"turn": 1}},
        }
        with self.assertRaisesRegex(ScenarioError, "hidden identity coverage"):
            Scenario(data)

    def test_semantic_choice_and_visible_assertions(self) -> None:
        scenario = Scenario(scene())
        self.assertEqual(scenario.first_player_role, "host")
        self.assertFalse(scenario.pregame_complete)
        with self.assertRaisesRegex(ScenarioError, "pregame selection incomplete"):
            scenario.decide("host", fixture())
        finish_pregame(scenario)
        response = scenario.decide("host", fixture())
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "c1"})
        self.assertEqual(scenario.remaining_steps(), {"host": 0, "guest": 0})
        with self.assertRaisesRegex(ScenarioError, "no scripted step"):
            scenario.decide("host", fixture())

    def test_pregame_rounds_and_first_player(self) -> None:
        data = scene()
        pregame = data["pregame"]
        assert isinstance(pregame, dict)
        pregame["host"] = ["rock", "scissors"]
        pregame["guest"] = ["rock", "paper"]
        scenario = Scenario(data)
        for role, expected in (
            ("host", "rock"),
            ("guest", "rock"),
            ("host", "scissors"),
            ("guest", "paper"),
        ):
            request = fixture("rock_paper_scissors")
            prompt = request["prompt"]
            assert isinstance(prompt, dict)
            prompt["candidates"] = [
                {"id": "r", "kind": "rock", "description": ""},
                {"id": "s", "kind": "scissors", "description": ""},
                {"id": "p", "kind": "paper", "description": ""},
            ]
            response = scenario.decide(role, request)
            self.assertEqual(
                response["action"],
                {
                    "kind": "choice",
                    "candidate_id": {"rock": "r", "scissors": "s", "paper": "p"}[expected],
                },
            )
        request = fixture("first_player")
        prompt = request["prompt"]
        assert isinstance(prompt, dict)
        prompt["candidates"] = [
            {"id": "f", "kind": "go_first", "description": ""},
            {"id": "s", "kind": "go_second", "description": ""},
        ]
        response = scenario.decide("host", request)
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "s"})
        self.assertTrue(scenario.pregame_complete)
        self.assertEqual(scenario.first_player_role, "guest")

    def test_ambiguous_selector_requires_explicit_ordinal(self) -> None:
        data = scene()
        steps = data["steps"]
        step = steps["host"][0]
        step["action"]["match"] = {"kind": "normal_summon", "card_id": "123"}
        scenario = Scenario(data)
        finish_pregame(scenario)
        with self.assertRaisesRegex(ScenarioError, "expected 1 matches, found 2"):
            scenario.decide("host", fixture())
        step["action"]["match"].update(expected_matches=2, ordinal=2)
        scenario = Scenario(data)
        finish_pregame(scenario)
        response = scenario.decide("host", fixture())
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "c1"})

    def test_rejects_unknown_fields_integer_card_id_duplicate_yaml_key(self) -> None:
        data = scene()
        data["extra"] = 1
        with self.assertRaisesRegex(ScenarioError, "unknown fields"):
            Scenario(data)
        data = scene()
        data["steps"]["host"][0]["action"]["match"]["card_id"] = 123
        with self.assertRaisesRegex(ScenarioError, "quoted decimal"):
            Scenario(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yaml"
            path.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ScenarioError, "duplicate YAML key"):
                Scenario.load(path)

    def test_exact_and_contains_visible_zones(self) -> None:
        scenario = Scenario(scene())
        observation = fixture()["observation"]
        scenario.assert_visible(
            "host",
            observation,
            {"zones": [{"player": 0, "name": "hand", "exact": [{"card_id": "123", "count": 2}]}]},
        )
        with self.assertRaisesRegex(ScenarioError, "extra cards"):
            scenario.assert_visible(
                "host",
                observation,
                {"zones": [{"player": 0, "name": "hand", "exact": [{"card_id": "123"}]}]},
            )

    def test_wait_for_recorded_after_validated_action(self) -> None:
        data = scene()
        data["steps"]["host"][0]["wait_for"] = {
            "timeout_ms": 5000,
            "expect": {"life_points": [8000, 8000]},
        }
        scenario = Scenario(data)
        finish_pregame(scenario)
        self.assertEqual(scenario.status()["wait_for"], [])
        scenario.decide("host", fixture())
        checkpoints = scenario.status()["wait_for"]
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]["role"], "host")
        self.assertEqual(checkpoints[0]["step_index"], 1)
        self.assertEqual(checkpoints[0]["timeout_ms"], 5000)
        self.assertGreater(checkpoints[0]["after_unix_ms"], 0)

    def test_candidate_description_id_disambiguates_effect(self) -> None:
        data = scene()
        data["steps"]["host"][0]["action"]["match"] = {
            "kind": "normal_summon",
            "description_id": 2,
        }
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture()
        request["prompt"]["candidates"][0]["description_id"] = 1
        request["prompt"]["candidates"][1]["description_id"] = 2
        response = scenario.decide("host", request)
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "c1"})

    def test_invalid_pregame_and_prompt_divergence(self) -> None:
        data = scene()
        data["pregame"] = {"host": "rock", "guest": "rock", "winner_chooses": "go_first"}
        with self.assertRaisesRegex(ScenarioError, "must end in a winner"):
            Scenario(data)
        scenario = Scenario(scene())
        finish_pregame(scenario)
        with self.assertRaisesRegex(ScenarioError, "expected prompt idle_command"):
            scenario.decide("host", fixture("chain"))

    def test_optional_decline_skips_unrelated_prompt_and_preserves_step(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "decline"}
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture("chain")
        request["prompt_id"] = 17
        request["prompt"]["candidates"] = [
            {"id": "a", "kind": "activate", "description": "发动"},
            {"id": "p", "kind": "pass", "description": "放弃"},
        ]
        response = scenario.decide("host", request)
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "p"})
        self.assertEqual(response["prompt_id"], 17)
        self.assertEqual(scenario.remaining_steps()["host"], 1)
        self.assertEqual(
            scenario.status()["ignored_decisions"],
            [
                {
                    "role": "host",
                    "prompt_id": 17,
                    "prompt_kind": "chain",
                    "candidates": [{"kind": "activate"}, {"kind": "pass"}],
                }
            ],
        )
        scenario.decide("host", fixture())
        self.assertEqual(scenario.remaining_steps()["host"], 0)

    def test_optional_decline_waits_for_visible_precondition(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "decline"}
        step = data["steps"]["host"][0]
        step["expect"] = {"prompt": "chain", "phase": "battle"}
        step["action"] = {"kind": "choice", "match": {"kind": "activate", "card_id": "123"}}
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture("chain")
        request["prompt"]["candidates"] = [
            {
                "id": "a",
                "kind": "activate",
                "description": "发动",
                "card": {
                    "instance_id": "i0",
                    "card_id": 123,
                    "controller": 0,
                    "location": "hand",
                    "sequence": 0,
                },
            },
            {"id": "p", "kind": "pass", "description": "放弃"},
        ]
        self.assertEqual(
            scenario.decide("host", request)["action"],
            {"kind": "choice", "candidate_id": "p"},
        )
        self.assertEqual(scenario.remaining_steps()["host"], 1)
        request["observation"]["phase"] = "battle"
        self.assertEqual(
            scenario.decide("host", request)["action"],
            {"kind": "choice", "candidate_id": "a"},
        )
        self.assertEqual(len(scenario.status()["ignored_decisions"]), 1)

    def test_optional_decline_skips_same_kind_without_scripted_candidate(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "decline"}
        data["steps"]["host"][0]["expect"] = {"prompt": "chain"}
        data["steps"]["host"][0]["action"] = {
            "kind": "choice",
            "match": {"kind": "activate", "card_id": "123"},
        }
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture("chain")
        request["prompt"]["candidates"] = [
            {"id": "other", "kind": "activate", "description": "其他效果"},
            {"id": "p", "kind": "pass", "description": "放弃"},
        ]
        self.assertEqual(
            scenario.decide("host", request)["action"],
            {"kind": "choice", "candidate_id": "p"},
        )
        self.assertEqual(scenario.remaining_steps()["host"], 1)

    def test_optional_decline_rejects_forced_or_ambiguous_action(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "decline"}
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture("effect_yes_no")
        request["prompt"]["candidates"] = [
            {"id": "a", "kind": "activate", "description": "发动"},
            {"id": "d", "kind": "decline", "description": "放弃"},
        ]
        self.assertEqual(
            scenario.decide("host", request)["action"],
            {"kind": "choice", "candidate_id": "d"},
        )
        request["prompt"]["candidates"].pop()
        with self.assertRaisesRegex(ScenarioError, "expected prompt idle_command"):
            scenario.decide("host", request)
        data["steps"]["host"][0]["expect"]["prompt"] = "chain"
        data["steps"]["host"][0]["action"]["match"] = {"kind": "activate"}
        scenario = Scenario(data)
        finish_pregame(scenario)
        request = fixture("chain")
        request["prompt"]["candidates"] = [
            {"id": "a1", "kind": "activate", "description": "发动一"},
            {"id": "a2", "kind": "activate", "description": "发动二"},
            {"id": "p", "kind": "pass", "description": "放弃"},
        ]
        with self.assertRaisesRegex(ScenarioError, "expected 1 matches, found 2"):
            scenario.decide("host", request)

    def test_optional_decline_schema_is_strict(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "pass"}
        with self.assertRaisesRegex(ScenarioError, "defaults.optional: expected decline"):
            Scenario(data)
        data["defaults"] = {"optional": "decline", "other": True}
        with self.assertRaisesRegex(ScenarioError, "unknown fields"):
            Scenario(data)

    def test_random_event_allowlist_and_surrender_goal(self) -> None:
        data = scene()
        data["allowed_random_events"] = ["hand_shuffle"]
        data["goal"] = {
            "kind": "duel_end",
            "winner": "guest",
            "surrender": {"role": "host", "expect": {"host": {}, "guest": {}}},
        }
        scenario = Scenario(data)
        self.assertEqual(scenario.allowed_random_messages, {33})
        for invalid in (["hand_shuffle", "hand_shuffle"], ["coin"], [0]):
            data["allowed_random_events"] = invalid
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ScenarioError, "only unique hand_shuffle"):
                    Scenario(data)
        data["allowed_random_events"] = []
        goal = cast(dict[str, Any], data["goal"])
        goal["winner"] = "host"
        with self.assertRaisesRegex(ScenarioError, "requires a duelist role"):
            Scenario(data)
        cast(dict[str, Any], goal["surrender"])["role"] = "guest"
        self.assertEqual(Scenario(data).goal["winner"], "host")
        goal["expect"] = {
            "host": {"zones": [{"player": "self", "name": "monster", "count": 1}]},
            "guest": {"life_points": [8000, 8000]},
        }
        self.assertEqual(Scenario(data).goal["expect"]["host"]["zones"][0]["player"], 0)
        del cast(dict[str, Any], goal["expect"])["guest"]
        with self.assertRaisesRegex(ScenarioError, "missing"):
            Scenario(data)

    def test_full_duel_fixture_parses(self) -> None:
        root = Path(__file__).resolve().parents[2]
        scenario = Scenario.load(root / "tests/scenarios/duel-001/scenario.yaml")
        self.assertEqual(scenario.goal["winner"], "guest")
        self.assertEqual(scenario.allowed_random_messages, {33})

    def test_ordered_event_assertions_validate_reveals_and_shuffle(self) -> None:
        data = scene()
        data["event_assertions"] = {
            "host": [
                {
                    "kind": "cards_revealed",
                    "cards": [
                        {"card_id": "05318639", "player": "opponent", "location": 2},
                        {"card_id": "27755794", "player": "opponent", "location": 2},
                    ],
                },
                {"kind": "shuffle_message_observed", "player": "opponent", "zone": "hand"},
            ]
        }
        scenario = Scenario(data)
        events = [
            {
                "event_id": 2,
                "kind": "cards_revealed",
                "cards": [
                    {"card_id": 27755794, "player": 1, "location": 2},
                    {"card_id": 5318639, "player": 1, "location": 2},
                ],
            },
            {"event_id": 3, "kind": "phase_changed"},
            {"event_id": 4, "kind": "shuffle_message_observed", "player": 1, "zone": "hand"},
        ]
        scenario.assert_events("host", events)
        with self.assertRaisesRegex(ScenarioError, "event_assertions\\[1\\]"):
            scenario.assert_events("host", events[:2])
        with self.assertRaisesRegex(ScenarioError, "event_assertions\\[0\\]"):
            scenario.assert_events("host", events[1:])
        cast(dict[str, Any], data["event_assertions"])["host"][0]["cards"][0]["card_id"] = 5318639
        with self.assertRaisesRegex(ScenarioError, "quoted decimal"):
            Scenario(data)

    def test_duel_002_event_assertions_parse(self) -> None:
        root = Path(__file__).resolve().parents[2]
        scenario = Scenario.load(root / "tests/scenarios/duel-002/scenario.yaml")
        self.assertEqual(len(scenario.event_assertions["host"]), 2)
        self.assertEqual(scenario.event_assertions["host"][0]["cards"][0]["card_id"], 5318639)

    def test_revealed_field_card_can_assert_public_sequence(self) -> None:
        data = scene()
        data["event_assertions"] = {
            "guest": [
                {
                    "kind": "cards_revealed",
                    "cards": [
                        {
                            "card_id": "89023486",
                            "player": "opponent",
                            "location": 8,
                            "sequence": 3,
                        }
                    ],
                }
            ]
        }
        scenario = Scenario(data)
        event = {
            "kind": "cards_revealed",
            "cards": [{"card_id": 89023486, "player": 1, "location": 8, "sequence": 3}],
        }
        scenario.assert_events("guest", [event])
        cast(dict[str, Any], event["cards"][0])["sequence"] = 2
        with self.assertRaisesRegex(ScenarioError, "event_assertions\\[0\\]"):
            scenario.assert_events("guest", [event])

    def test_position_change_and_hidden_identity_assertions(self) -> None:
        data = scene()
        data["event_assertions"] = {
            "host": [
                {
                    "kind": "effect_activated",
                    "card_id": "02326738",
                    "controller": "opponent",
                    "location": 4,
                    "sequence": 0,
                },
                {
                    "kind": "position_changed",
                    "player": "opponent",
                    "location": 4,
                    "sequence": 0,
                    "from_position": "face_up_attack",
                    "to_position": "face_down_defense",
                },
            ]
        }
        scenario = Scenario(data)
        activated = {
            "kind": "effect_activated",
            "card_id": 2326738,
            "controller": 1,
            "location": 4,
            "sequence": 0,
        }
        event = {
            "kind": "position_changed",
            "player": 1,
            "location": 4,
            "sequence": 0,
            "from_position": "face_up_attack",
            "to_position": "face_down_defense",
        }
        scenario.assert_events("host", [activated, event])
        changed = dict(event, sequence=1)
        with self.assertRaisesRegex(ScenarioError, "event_assertions\\[1\\]"):
            scenario.assert_events("host", [activated, changed])
        with self.assertRaisesRegex(ScenarioError, "event_assertions\\[0\\]"):
            scenario.assert_events("host", [event])

        hidden = {
            "zones": [
                {
                    "player": 1,
                    "name": "monster",
                    "count": 1,
                    "cards": [{"known": False, "position": "face_down_defense", "sequence": 0}],
                }
            ]
        }
        expected = {
            "zones": [
                {
                    "player": 1,
                    "name": "monster",
                    "count": 1,
                    "contains": [{"known": False, "position": "face_down_defense", "sequence": 0}],
                }
            ]
        }
        scenario.assert_visible("host", hidden, expected)
        visible = {
            "zones": [
                {
                    "player": 1,
                    "name": "monster",
                    "count": 1,
                    "cards": [{"known": True, "position": "face_down_defense", "sequence": 0}],
                }
            ]
        }
        with self.assertRaisesRegex(ScenarioError, "visible zone"):
            scenario.assert_visible("host", visible, expected)

    def test_gui_pacing_skips_automatic_optional_decline(self) -> None:
        data = scene()
        data["defaults"] = {"optional": "decline"}
        scenario = Scenario(data)
        finish_pregame(scenario)
        with tempfile.TemporaryDirectory() as directory:
            server = ScenarioDecisionServer.__new__(ScenarioDecisionServer)
            server.scenario = scenario
            server.digest = "a" * 64
            server.status_path = Path(directory) / "status.json"
            server.decisions = 0
            server.last_action_unix_ms = 0
            server.failure = None
            server.step_delay = 1
            optional = fixture("chain")
            optional["prompt"]["candidates"] = [
                {"id": "a", "kind": "activate", "description": "发动"},
                {"id": "p", "kind": "pass", "description": "放弃"},
            ]
            optional["observation"]["test_role"] = "host"
            scripted = fixture()
            scripted["observation"]["test_role"] = "host"
            with patch("agent_sdk.scenario_server.time.sleep") as sleep:
                server.decide(optional)
                sleep.assert_not_called()
                server.decide(scripted)
                sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
