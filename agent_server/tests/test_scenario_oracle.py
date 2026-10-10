"""The v3 offline child can obtain scripted actions from a local coordinator."""

from __future__ import annotations

import unittest
from typing import Any

from agent_sdk.contract import parse_request
from agent_sdk.state import StateDelta
from aiohttp import web
from aiohttp.test_utils import TestServer
from test_decision_session import request

from agent_server.__main__ import scenario_oracle_decide, scenario_oracle_url
from agent_server.duel_tools import DecisionFailure


class ScenarioOracleTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_coordinator_receives_full_v3_request(self) -> None:
        seen: list[dict[str, Any]] = []

        async def action(http_request: web.Request) -> web.Response:
            self.assertEqual(http_request.headers["Authorization"], "Bearer " + "s" * 32)
            seen.append(await http_request.json())
            return web.json_response(
                {
                    "schema_version": 3,
                    "action": {"kind": "choice", "candidate_id": "c0"},
                    "reason": "剧本动作",
                }
            )

        app = web.Application()
        app.router.add_post("/v3/scenario-action", action)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            url = scenario_oracle_url(str(server.make_url("/v3/scenario-action")))
            body = request()
            hand: dict[str, Any] = {"player": 0, "name": "hand", "count": 0, "cards": []}
            body["observation"]["zones"].append(hand)
            queries: list[dict[str, Any]] = []

            async def query_client(query: dict[str, Any]) -> dict[str, Any]:
                queries.append(query)
                return {"kind": "inspect_zone", "zone": hand}

            decide = scenario_oracle_decide(url, "s" * 32)
            result = await decide(parse_request(body), StateDelta(1, 0, (), ()), query_client)
            self.assertEqual(result, ({"kind": "choice", "candidate_id": "c0"}, "剧本动作"))
            self.assertEqual(queries, [{"kind": "inspect_zone", "player": 0, "zone": "hand"}])
            await decide(parse_request(body), StateDelta(1, 0, (), ()), query_client)
            self.assertEqual(queries, [{"kind": "inspect_zone", "player": 0, "zone": "hand"}])
            self.assertEqual(seen, [body, body])
        finally:
            await server.close()

    async def test_invalid_action_is_rejected(self) -> None:
        async def action(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "schema_version": 3,
                    "action": {"kind": "choice", "candidate_id": "bad"},
                    "reason": "x",
                }
            )

        app = web.Application()
        app.router.add_post("/v3/scenario-action", action)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            url = scenario_oracle_url(str(server.make_url("/v3/scenario-action")))

            async def unused_query(_query: dict[str, Any]) -> dict[str, Any]:
                self.fail("test request has no visible own hand")

            with self.assertRaises(DecisionFailure) as raised:
                await scenario_oracle_decide(url, "s" * 32)(
                    parse_request(request()), StateDelta(1, 0, (), ()), unused_query
                )
            self.assertEqual(raised.exception.code, "scenario_mismatch")
        finally:
            await server.close()

    def test_oracle_url_is_local_and_fixed(self) -> None:
        for value in (
            "https://127.0.0.1:8000/v3/scenario-action",
            "http://localhost.evil:8000/v3/scenario-action",
            "http://127.0.0.1:8000/other",
            "http://127.0.0.1:8000/v3/scenario-action?x=1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scenario_oracle_url(value)
        with self.assertRaises(ValueError):
            scenario_oracle_decide("http://127.0.0.1:8000/v3/scenario-action", "short")
