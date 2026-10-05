import copy
import json
import unittest

from agent_sdk import (
    ContractError,
    UnsupportedPrompt,
    build_response,
    match_candidates,
    parse_request,
    validate_action,
    validate_response,
)


def fixture(
    kind: str = "idle_command", constraints: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": "s",
        "duel_id": "d",
        "prompt_id": 1,
        "database_sha256": "a" * 64,
        "deadline_unix_ms": None,
        "observation": {
            "self_player": 0,
            "turn_player": 1,
            "turn": 1,
            "phase": "main_1",
            "life_points": [8000, 8000],
            "zones": [],
            "events": [],
        },
        "prompt": {
            "kind": kind,
            "description": "选择",
            "constraints": constraints or {},
            "candidates": [
                {
                    "id": "c0",
                    "kind": (
                        "normal_summon"
                        if kind == "idle_command"
                        else "race"
                        if kind == "announce_race"
                        else "card"
                    ),
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
                    "kind": (
                        "normal_summon"
                        if kind == "idle_command"
                        else "race"
                        if kind == "announce_race"
                        else "card"
                    ),
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


class ContractTests(unittest.TestCase):
    def test_exact_identity_resolves_duplicate_card_code(self) -> None:
        request = parse_request(fixture())
        self.assertEqual(match_candidates(request, {"card_id": 123}), ["c0", "c1"])
        with self.assertRaises(ContractError):
            build_response(request, {"kind": "choice", "selector": {"card_id": 123}}, "原因")
        response = build_response(
            request, {"kind": "choice", "selector": {"instance_id": "i1"}}, "原因"
        )
        self.assertEqual(response["action"], {"kind": "choice", "candidate_id": "c1"})
        self.assertEqual(validate_response(request, json.dumps(response)), response)

    def test_stale_and_boolean_correlations_rejected(self) -> None:
        request = parse_request(fixture())
        response = build_response(request, {"kind": "choice", "candidate_id": "c0"}, "")
        for value in (2, True):
            changed = copy.deepcopy(response)
            changed["prompt_id"] = value
            with self.assertRaises(ContractError):
                validate_response(request, changed)

    def test_json_duplicate_nonfinite_and_bad_hash_rejected(self) -> None:
        for value in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', '{"x":1e999}'):
            with self.assertRaises(ContractError):
                parse_request(value)
        data = fixture()
        data["database_sha256"] = "A" * 64
        with self.assertRaises(ContractError):
            parse_request(data)

    def test_request_is_detached_and_optional_extensions_allowed(self) -> None:
        data = fixture()
        data["future_feature"] = {"enabled": True}
        request = parse_request(data)
        data["session_id"] = "changed"
        self.assertEqual(request.data["session_id"], "s")

    def test_raw_protocol_and_unknown_constraints_rejected(self) -> None:
        request = parse_request(fixture())
        for action in (
            {"kind": "choice", "candidate_id": "c0", "ctos": 5},
            {"kind": "choice", "candidate_id": "other"},
            {"kind": "raw", "value": 5},
        ):
            with self.assertRaises(ContractError):
                validate_action(request, action)
        request = parse_request(fixture(constraints={"unrecognized": 1}))
        with self.assertRaises(UnsupportedPrompt):
            validate_action(request, {"kind": "choice", "candidate_id": "c0"})

    def test_card_count_duplicates_and_mandatory(self) -> None:
        request = parse_request(fixture("select_card", {"min_count": 1, "max_count": 2}))
        request.candidates[0]["mandatory"] = True
        for ids in (["c1"], ["c0", "c0"], []):
            with self.assertRaises(ContractError):
                validate_action(request, {"kind": "select_cards", "candidate_ids": ids})
        validate_action(request, {"kind": "select_cards", "candidate_ids": ["c0", "c1"]})

    def test_tribute_weight_is_distinct_from_card_count(self) -> None:
        request = parse_request(
            fixture("tribute", {"min_count": 1, "max_count": 2, "min_weight": 2, "max_weight": 2})
        )
        request.candidates[0]["weight"] = 2
        request.candidates[1]["weight"] = 1
        validate_action(request, {"kind": "select_cards", "candidate_ids": ["c0"]})
        with self.assertRaises(ContractError):
            validate_action(request, {"kind": "select_cards", "candidate_ids": ["c1"]})

    def test_sum_alternative_values_and_minimal_at_least(self) -> None:
        request = parse_request(
            fixture("sum", {"min_count": 1, "max_count": 2, "mode": "exact", "target": 7})
        )
        request.candidates[0]["value_options"] = [2, 4]
        request.candidates[1]["value_options"] = [3]
        action = {"kind": "select_cards", "candidate_ids": ["c0", "c1"]}
        validate_action(request, action)
        constraints = request.prompt["constraints"]
        assert isinstance(constraints, dict)
        constraints.update(mode="at_least", target=4)
        validate_action(request, action)
        constraints["target"] = 2
        with self.assertRaises(ContractError):
            validate_action(request, action)
        request.candidates[0].pop("value_options")
        with self.assertRaises(UnsupportedPrompt):
            validate_action(request, action)

    def test_sort_is_complete_permutation(self) -> None:
        request = parse_request(fixture("sort", {"count": 2}))
        for candidate in request.candidates:
            candidate["kind"] = "card"
        validate_action(request, {"kind": "select_cards", "candidate_ids": ["c1", "c0"]})
        with self.assertRaises(ContractError):
            validate_action(request, {"kind": "select_cards", "candidate_ids": ["c0"]})

    def test_place_membership_and_uniqueness(self) -> None:
        request = parse_request(fixture("place", {"count": 1}))
        for index, candidate in enumerate(request.candidates):
            candidate.update(controller=0, location="mzone", sequence=index)
        place = {"controller": 0, "location": "mzone", "sequence": 0}
        validate_action(request, {"kind": "select_places", "places": [place]})
        with self.assertRaises(ContractError):
            validate_action(
                request, {"kind": "select_places", "places": [{**place, "sequence": 7}]}
            )

    def test_counter_capacity_total_and_duplicate(self) -> None:
        request = parse_request(fixture("counter", {"total_count": 3}))
        request.candidates[0]["max_count"] = 2
        request.candidates[1]["max_count"] = 2
        validate_action(
            request,
            {
                "kind": "distribute_counters",
                "allocations": [
                    {"candidate_id": "c0", "count": 1},
                    {"candidate_id": "c1", "count": 2},
                ],
            },
        )
        for allocations in (
            [{"candidate_id": "c0", "count": 3}],
            [{"candidate_id": "c0", "count": 1}],
            [{"candidate_id": "c0", "count": 1}, {"candidate_id": "c0", "count": 2}],
        ):
            with self.assertRaises(ContractError):
                validate_action(
                    request, {"kind": "distribute_counters", "allocations": allocations}
                )

    def test_announce_filter_fails_closed(self) -> None:
        request = parse_request(fixture("announce_card", {"allowed_card_ids": [123]}))
        validate_action(request, {"kind": "announce_card", "card_id": 123})
        with self.assertRaises(ContractError):
            validate_action(request, {"kind": "announce_card", "card_id": 456})
        request = parse_request(fixture("announce_card"))
        with self.assertRaises(UnsupportedPrompt):
            validate_action(request, {"kind": "announce_card", "card_id": 123})

    def test_unpublished_and_duplicate_candidates_rejected(self) -> None:
        raw = json.dumps(fixture())
        with self.assertRaises(ContractError):
            parse_request(raw.replace('"id": "c1"', '"id": "c0"'))
        with self.assertRaises(ContractError):
            parse_request(raw.replace('"card_id": 123', '"card_id": 123, "public": false'))
        with self.assertRaises(ContractError):
            parse_request(raw.replace('"controller": 0', '"controller": true'))

    def test_announcement_bits_and_step_prompt(self) -> None:
        request = parse_request(fixture("announce_race", {"count": 1}))
        request.candidates[0]["bit"] = 1
        request.candidates[1]["bit"] = 2
        validate_action(request, {"kind": "select_cards", "candidate_ids": ["c1"]})
        request.candidates[1]["bit"] = 3
        with self.assertRaises(ContractError):
            validate_action(request, {"kind": "select_cards", "candidate_ids": ["c1"]})
        request = parse_request(fixture("unselect_card", {"cancelable": True}))
        validate_action(request, {"kind": "select_step", "candidate_id": "c0"})
        with self.assertRaises(UnsupportedPrompt):
            validate_action(request, {"kind": "choice", "candidate_id": "c0"})

    def test_action_kind_bound_to_prompt(self) -> None:
        request = parse_request(fixture("select_card", {"count": 1}))
        with self.assertRaises(UnsupportedPrompt):
            validate_action(request, {"kind": "choice", "candidate_id": "c0"})


if __name__ == "__main__":
    unittest.main()
