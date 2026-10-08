"""Pydantic AI integration with a local deterministic model."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_sdk.contract import parse_request
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_decision_session import request

from agent_server.config import load_settings
from agent_server.decision_session import DecisionManager
from agent_server.model_agent import DecisionAgent, intent_format
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_writes_hand_note_and_next_turn_receives_it(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                prompts: list[dict[str, Any]] = []
                calls = 0

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    user_parts = [
                        part.content
                        for message in messages
                        if isinstance(message, ModelRequest)
                        for part in message.parts
                        if isinstance(part, UserPromptPart)
                    ]
                    assert isinstance(user_parts[-1], str)
                    prompts.append(json.loads(user_parts[-1]))
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "write_zone_note",
                                    {
                                        "player": 1,
                                        "zone": "hand",
                                        "note": "对手展示了旋风；手牌中曾有此卡，当前位置未知。",
                                        "evidence_event_ids": [1],
                                    },
                                )
                            ]
                        )
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

                first_body = request()
                first_body["observation"]["events"] = [
                    {
                        "event_id": 1,
                        "kind": "cards_revealed",
                        "message_type": 31,
                        "cards": [{"player": 1, "location": 2, "card_id": 5318639}],
                    }
                ]
                first = parse_request(first_body)
                await agent.decide(first, storage.apply_decision(first.data), unused_query)
                self.assertEqual(prompts[0]["opponent_hand_note"]["status"], "unwritten")
                self.assertEqual(
                    len(storage.get_records("client-a", "duel-1", kind="hand_note_revision")), 1
                )

                second_body = request()
                second_body["prompt_id"] = 2
                second_body["state_version"] = 2
                second_body["observation"]["events"] = [
                    {
                        "event_id": 2,
                        "kind": "shuffle_message_observed",
                        "message_type": 33,
                        "player": 1,
                        "zone": "hand",
                    }
                ]
                second = parse_request(second_body)
                await agent.decide(second, storage.apply_decision(second.data), unused_query)
                self.assertEqual(
                    prompts[-1]["opponent_hand_note"]["note"],
                    "对手展示了旋风；手牌中曾有此卡，当前位置未知。",
                )
                self.assertTrue(prompts[-1]["opponent_hand_note"]["newer_events_exist"])
                self.assertEqual(prompts[-1]["new_events"][0]["event_id"], 2)

    async def test_first_model_turn_receives_confirmed_state_then_deltas(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                prompts: list[dict[str, Any]] = []

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    user_parts = [
                        part.content
                        for message in messages
                        if isinstance(message, ModelRequest)
                        for part in message.parts
                        if isinstance(part, UserPromptPart)
                    ]
                    last_prompt = user_parts[-1]
                    assert isinstance(last_prompt, str)
                    prompts.append(json.loads(last_prompt))
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

                first = parse_request(request())
                first_delta = storage.apply_decision(first.data)
                await agent.decide(first, first_delta, unused_query)
                self.assertEqual(
                    prompts[0]["initial_state"], storage.get_state("client-a", "duel-1", 1)
                )
                self.assertEqual(prompts[0]["net_changes"], [{"kind": "initial_snapshot"}])

                second_body = request()
                second_body["state_version"] = 2
                second_body["prompt_id"] = 2
                second_body["observation"]["life_points"] = [7500, 8000]
                second = parse_request(second_body)
                second_delta = storage.apply_decision(second.data)
                await agent.decide(second, second_delta, unused_query)
                self.assertNotIn("initial_state", prompts[1])
                self.assertEqual(prompts[1]["net_changes"], list(second_delta.changes))

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
                self.assertIn("provider_request_started", [item["kind"] for item in traces])
                self.assertIn("provider_request_finished", [item["kind"] for item in traces])
                self.assertIn("decision_timing", [item["kind"] for item in traces])
                request_end = next(
                    item for item in traces if item["kind"] == "provider_request_finished"
                )
                self.assertGreaterEqual(request_end["payload"]["duration_ms"], 0)
                self.assertIn("usage", request_end["payload"])

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

    async def test_none_effort_does_not_request_reasoning_summary(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                settings = load_settings(root, offline=True)
                settings.model.reasoning_effort = "none"
                agent = DecisionAgent(
                    settings,
                    storage,
                    SkillResources(root),
                    model=FunctionModel(lambda _messages, _info: ModelResponse([])),
                )
                request_settings = agent._request_settings()  # pyright: ignore[reportPrivateUsage]
                self.assertEqual(request_settings.get("openai_reasoning_effort"), "none")
                self.assertNotIn("openai_reasoning_summary", request_settings)

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
