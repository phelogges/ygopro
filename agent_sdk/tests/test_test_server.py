from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import cast

from agent_sdk import UnsupportedPrompt, parse_request, validate_response
from agent_sdk.contract import JSON, Object
from agent_sdk.test_server import DecisionError, DecisionServer, database_digest, decide


def request(
    kind: str = "idle_command",
    constraints: Object | None = None,
    candidates: list[Object] | None = None,
) -> Object:
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
            "turn": 2,
            "phase": "main_1",
            "life_points": [8000, 8000],
            "zones": [],
            "events": [],
        },
        "prompt": {
            "kind": kind,
            "description": "",
            "constraints": constraints or {},
            "candidates": cast(list[JSON], candidates or []),
        },
    }


def candidate(cid: str, kind: str = "card", **extra: JSON) -> Object:
    return {"id": cid, "kind": kind, "description": "", **extra}


class PolicyTests(unittest.TestCase):
    def check(self, value: Object) -> Object:
        response = decide(value, "a" * 64)
        validate_response(parse_request(value), response)
        return cast(Object, response["action"])

    def test_e2e_peers_do_not_tie_every_rock_paper_scissors_round(self) -> None:
        value = request(
            "rock_paper_scissors",
            candidates=[candidate("rock", "rock"), candidate("paper", "paper")],
        )
        observation = cast(Object, value["observation"])
        observation["test_role"] = "host"
        self.assertEqual(self.check(value)["candidate_id"], "rock")
        observation["test_role"] = "guest"
        self.assertEqual(self.check(value)["candidate_id"], "paper")

    def test_optional_place_prefers_placement_over_cancel(self) -> None:
        value = request(
            "select_place",
            {"min_count": 0, "max_count": 1, "cancelable": True},
            [candidate("zone", "place", controller=0, location="spell", sequence=0)],
        )
        self.assertEqual(
            self.check(value),
            {
                "kind": "select_places",
                "places": [{"controller": 0, "location": "spell", "sequence": 0}],
            },
        )

    def test_summon_prepare_attack_then_advance(self) -> None:
        value = request(
            candidates=[
                candidate("a", "activate"),
                candidate("s", "normal_summon"),
                candidate("b", "battle_phase"),
            ]
        )
        self.assertEqual(self.check(value)["candidate_id"], "s")
        value = request(
            "battle_command", candidates=[candidate("e", "end_turn"), candidate("a", "attack")]
        )
        self.assertEqual(self.check(value)["candidate_id"], "a")
        value = request("battle_command", candidates=[candidate("e", "end_turn")])
        self.assertEqual(self.check(value)["candidate_id"], "e")

    def test_no_reversible_effect_loop(self) -> None:
        with self.assertRaises(UnsupportedPrompt):
            self.check(request(candidates=[candidate("a", "activate")]))

    def test_decline_and_pass(self) -> None:
        self.assertEqual(
            self.check(
                request(
                    "effect_yes_no",
                    candidates=[candidate("y", "accept"), candidate("n", "decline")],
                )
            )["candidate_id"],
            "n",
        )
        self.assertEqual(
            self.check(
                request("chain", candidates=[candidate("a", "activate"), candidate("p", "pass")])
            )["candidate_id"],
            "p",
        )

    def test_sum_uses_valid_combination_and_mandatory(self) -> None:
        value = request(
            "sum",
            {"min_count": 2, "max_count": 3, "mode": "exact", "target": 7},
            [
                candidate("m", mandatory=True, value_options=[2]),
                candidate("a", value_options=[3]),
                candidate("b", value_options=[5]),
            ],
        )
        self.assertEqual(self.check(value)["candidate_ids"], ["m", "b"])

    def test_tribute_places_and_counters(self) -> None:
        value = request(
            "tribute",
            {"min_count": 1, "max_count": 2, "min_weight": 2, "max_weight": 2},
            [candidate("a", weight=1), candidate("b", weight=2)],
        )
        self.assertEqual(self.check(value)["candidate_ids"], ["b"])
        value = request(
            "place",
            {"count": 1},
            [candidate("p", "place", controller=0, location="mzone", sequence=2)],
        )
        self.assertEqual(self.check(value)["kind"], "select_places")
        value = request(
            "counter",
            {"total_count": 3},
            [candidate("a", max_count=2), candidate("b", max_count=2)],
        )
        self.assertEqual(
            self.check(value)["allocations"],
            [{"candidate_id": "a", "count": 2}, {"candidate_id": "b", "count": 1}],
        )

    def test_unselect_finish_and_unknown_constraints(self) -> None:
        value = request(
            "select_unselect_card",
            candidates=[candidate("u", "unselect"), candidate("f", "finish")],
        )
        self.assertEqual(self.check(value)["candidate_id"], "f")
        with self.assertRaises(UnsupportedPrompt):
            self.check(request("option", {"unknown": 1}, [candidate("o", "option")]))

    def test_hash_and_deadline_failures(self) -> None:
        value = request(candidates=[candidate("e", "end_turn")])
        with self.assertRaises(DecisionError) as error:
            decide(value, "b" * 64)
        self.assertEqual(error.exception.code, "database_mismatch")
        value["deadline_unix_ms"] = 0
        with self.assertRaises(DecisionError) as error:
            decide(value, "a" * 64)
        self.assertEqual(error.exception.code, "timeout")

    def test_real_file_hash_and_bind_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cards.cdb"
            path.write_bytes(b"abc")
            self.assertEqual(database_digest(path), hashlib.sha256(b"abc").hexdigest())
            for allow_lan, token in [(False, ""), (True, ""), (False, "secret")]:
                with self.assertRaises(ValueError):
                    DecisionServer("0.0.0.0", 0, path, token, allow_lan=allow_lan)
            with self.assertRaises(FileNotFoundError):
                database_digest(Path(directory) / "missing.cdb")


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "cards.cdb"
        path.write_bytes(b"actual database fixture")
        self.server = DecisionServer(
            "127.0.0.1", 0, path, "secret", state_dir=Path(self.directory.name) / "state"
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def post(
        self,
        body: str,
        *,
        path: str = "/v1/decision",
        token: str = "secret",
        content_type: str = "application/json",
    ) -> tuple[int, Object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(
                "POST",
                path,
                body.encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            )
            response = connection.getresponse()
            return response.status, cast(Object, json.loads(response.read()))
        finally:
            connection.close()

    def test_transport_auth_hash_and_correlation(self) -> None:
        value = request(candidates=[candidate("e", "end_turn")])
        value["database_sha256"] = self.server.digest
        status, response = self.post(json.dumps(value))
        self.assertEqual(status, 200)
        validate_response(parse_request(value), response)
        self.assertEqual(self.post(json.dumps(value), token="wrong")[0], 401)
        self.assertEqual(self.post(json.dumps(value), path="/wrong")[0], 404)
        self.assertEqual(self.post(json.dumps(value), content_type="text/plain")[0], 415)
        value["database_sha256"] = "b" * 64
        status, response = self.post(json.dumps(value))
        self.assertEqual(status, 409)
        self.assertEqual(cast(Object, response["error"])["code"], "database_mismatch")

    def test_size_json_and_fail_closed(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(
                "POST",
                "/v1/decision",
                headers={
                    "Authorization": "Bearer secret",
                    "Content-Type": "application/json",
                    "Content-Length": str(1024 * 1024 + 1),
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.post('{"x":1,"x":2}')[0], 400)
        value = request(candidates=[candidate("a", "activate")])
        value["database_sha256"] = self.server.digest
        status, response = self.post(json.dumps(value))
        self.assertEqual(status, 422)
        self.assertNotIn("action", response)

    def test_v2_decision_sync_and_status(self) -> None:
        value = request(candidates=[candidate("e", "end_turn")])
        value.update(schema_version=2, state_version=1, history_complete=True)
        value["database_sha256"] = self.server.digest
        observation = cast(Object, value["observation"])
        observation["events"] = [{"event_id": 1, "kind": "turn_started", "message_type": 40}]
        status, response = self.post(json.dumps(value), path="/v2/decision")
        self.assertEqual(status, 200)
        self.assertEqual(response["ack_event_id"], 1)
        validate_response(parse_request(value), response)
        status, replay = self.post(json.dumps(value), path="/v2/decision")
        self.assertEqual(status, 200)
        self.assertEqual(replay, response)
        identity = {
            key: value[key]
            for key in ("schema_version", "session_id", "duel_id", "database_sha256")
        }
        status, state = self.post(json.dumps(identity), path="/v2/status")
        self.assertEqual((status, state["state_version"], state["ack_event_id"]), (200, 1, 1))
        sync = {
            **identity,
            "history_complete": True,
            "events": [{"event_id": 2, "kind": "phase_changed", "message_type": 41}],
        }
        status, acknowledgment = self.post(json.dumps(sync), path="/v2/sync")
        self.assertEqual((status, acknowledgment["ack_event_id"]), (200, 2))


if __name__ == "__main__":
    unittest.main()
