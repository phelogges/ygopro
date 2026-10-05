"""Wire-shaped fixtures following decision_codec.cpp prompt construction."""

import unittest

from test_test_server import candidate, request

from agent_sdk import ContractError, parse_request, validate_action
from agent_sdk.contract import Object
from agent_sdk.test_server import decide


class CodecCompatibilityTests(unittest.TestCase):
    def test_sort_omits_default_but_accepts_explicit_default_choice(self) -> None:
        value = request(
            "sort", {"count": 2}, [candidate("c0"), candidate("c1"), candidate("c2", "default")]
        )
        parsed = parse_request(value)
        validate_action(parsed, {"kind": "choice", "candidate_id": "c2"})
        validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["c1", "c0"]})
        self.assertEqual(
            decide(value, "a" * 64)["action"],
            {"kind": "select_cards", "candidate_ids": ["c0", "c1"]},
        )
        with self.assertRaises(ContractError):
            validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["c0", "c1", "c2"]})

    def test_cancel_select_and_tribute_are_choices(self) -> None:
        for kind in ("select_cards", "tribute"):
            constraints: Object = {"min_count": 1, "max_count": 1, "cancelable": True}
            if kind == "tribute":
                constraints.update(min_weight=2, max_weight=1)
                # Production supplies max_weight=sum(all weights), below min_weight
                # when no legal tribute exists; cancellation must remain available.
            value = request(kind, constraints, [candidate("cancel", "cancel")])
            parsed = parse_request(value)
            action = {"kind": "choice", "candidate_id": "cancel"}
            validate_action(parsed, action)
            self.assertEqual(decide(value, "a" * 64)["action"], action)
            with self.assertRaises(ContractError):
                validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["cancel"]})

    def test_sum_count_includes_mandatory(self) -> None:
        parsed = parse_request(
            request(
                "sum",
                {"mode": "exact", "target": 7, "min_count": 2, "max_count": 2},
                [
                    candidate("mandatory", value_options=[4], mandatory=True),
                    candidate("optional", value_options=[3], mandatory=False),
                ],
            )
        )
        action = {"kind": "select_cards", "candidate_ids": ["mandatory", "optional"]}
        validate_action(parsed, action)
        with self.assertRaises(ContractError):
            validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["optional"]})
        self.assertEqual(decide(parsed.data, "a" * 64)["action"], action)

    def test_at_least_uses_min_max_envelope_including_mandatory(self) -> None:
        parsed = parse_request(
            request(
                "sum",
                {"mode": "at_least", "target": 11, "min_count": 2, "max_count": 255},
                [
                    candidate("c0", value_options=[1, 10], mandatory=True),
                    candidate("c1", value_options=[1, 10], mandatory=False),
                ],
            )
        )
        # Engine accepts max_sum=20 and min_sum-minimum=1 < 11 even though
        # no exact value assignment satisfies the old removal-based criterion.
        validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["c0", "c1"]})

    def test_tribute_has_no_engine_max_weight(self) -> None:
        parsed = parse_request(
            request(
                "tribute",
                {"min_count": 0, "max_count": 1, "min_weight": 2},
                [candidate("c0", weight=3)],
            )
        )
        validate_action(parsed, {"kind": "select_cards", "candidate_ids": ["c0"]})

    def test_unselect_finish_accepts_choice(self) -> None:
        parsed = parse_request(
            request("select_unselect_card", {"cancelable": True}, [candidate("done", "finish")])
        )
        validate_action(parsed, {"kind": "choice", "candidate_id": "done"})
        validate_action(parsed, {"kind": "select_step", "candidate_id": "done"})
