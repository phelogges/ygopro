"""Pydantic AI integration with a local deterministic model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_sdk.contract import parse_request
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_decision_session import request

from agent_server.config import load_settings
from agent_server.decision_session import DecisionManager
from agent_server.model_agent import DecisionAgent, intent_format
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_intent_format_uses_action_kind_for_guessing_prompt(self) -> None:
        body = request()
        body["prompt"] = {
            "kind": "rock_paper_scissors",
            "description": "请选择石头、剪刀或布",
            "constraints": {},
            "candidates": [
                {"id": "c0", "kind": "rock", "description": "石头"},
                {"id": "c1", "kind": "scissors", "description": "剪刀"},
            ],
        }
        guidance = intent_format(parse_request(body))
        self.assertEqual(guidance["formats"], [{"kind": "choice", "candidate_id": "<所选候选 id>"}])

    async def test_streamed_model_response_writes_timeline(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                parsed = parse_request(request())
                delta = storage.apply_decision(parsed.data)

                async def stream(_messages: object, _info: object):
                    yield {
                        0: DeltaToolCall(
                            name="final_result",
                            json_args='{"reason":"结束阶段","intent":{"kind":"choice","candidate_id":"c0"}}',
                        )
                    }

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(stream_function=stream),
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                action, _reason = await agent.decide(parsed, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                traces = storage.get_traces("client-a", "duel-1")
                self.assertIn("model_response_started", [item["kind"] for item in traces])
                self.assertIn("model_response_finished", [item["kind"] for item in traces])
                self.assertIn("model_decision", [item["kind"] for item in traces])

    async def test_live_startup_probe_requires_tool_and_output(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: object, _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse([ToolCallPart("probe_echo", {"value": "ready"})])
                    return ModelResponse([ToolCallPart("final_result", {"ok": True})])

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )
                await agent.probe()
                self.assertEqual(calls, 2)

    async def test_testmodel_runs_through_pydantic_agent(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                parsed = parse_request(request())
                delta = storage.apply_decision(parsed.data)

                async def respond(_messages: object, _info: object) -> ModelResponse:
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "结束阶段",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                action, reason = await agent.decide(parsed, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertTrue(reason)
                records = storage.get_records("client-a", "duel-1", kind="model_exchange")
                self.assertEqual(len(records), 1)

    async def test_monty_calls_release_local_card_tool(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                parsed = parse_request(request())
                delta = storage.apply_decision(parsed.data)
                calls = 0

                async def respond(_messages: object, _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        code = "card = await card_by_id(card_id=89631139)\ncard['id']"
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {"code": code},
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "已查阅卡片资料",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("client query was not requested")

                action, _reason = await agent.decide(parsed, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertEqual(calls, 2)
                record = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(record["payload"]["tool_attempts"][0]["name"], "card_by_id")

    async def test_monty_client_query_round_trip(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: object, _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        code = "await client_inspect_zone(player=0, zone='graveyard')"
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {"code": code},
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "墓地已确认",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )
                manager = DecisionManager(storage, agent.decide)
                query = await manager.decision(parse_request(request()))
                self.assertEqual(query["kind"], "query")
                self.assertEqual(
                    query["query"], {"kind": "inspect_zone", "player": 0, "zone": "graveyard"}
                )
                response: dict[str, Any] = {
                    **{
                        key: query[key]
                        for key in (
                            "schema_version",
                            "session_id",
                            "duel_id",
                            "prompt_id",
                            "state_version",
                            "query_id",
                        )
                    },
                    "result": {
                        "kind": "inspect_zone",
                        "zone": {"player": 0, "name": "graveyard", "count": 0, "cards": []},
                    },
                }
                action = await manager.query_result(response)
                self.assertEqual(action["kind"], "action")
                self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
