import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_sdk.scenario import Scenario, ScenarioError


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


if __name__ == "__main__":
    unittest.main()
