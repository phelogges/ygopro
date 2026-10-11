"""Pydantic AI integration with a local deterministic model."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import parse_request
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_decision_session import request

from agent_server.config import load_settings
from agent_server.model_agent import DecisionAgent, intent_format, model_visible_prompt
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_card_name_search_is_available_in_code_mode(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {
                                        "code": (
                                            "names = await search_card_names(keyword='地狱亡灵')\n"
                                            "names['matches'][0]['card_id']"
                                        )
                                    },
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择当前合法动作",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )
                parsed = parse_request(request())

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("card-name search must not query client")

                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                records = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(
                    records["payload"]["tool_attempts"][0]["name"], "search_card_names"
                )

    async def test_announce_card_model_input_omits_allowed_ids(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                card_id = 987654321
                body = request()
                body["deadline_unix_ms"] = int(time.time() * 1000) + 120_000
                body["prompt"] = {
                    "kind": "announce_card",
                    "description": "请宣言卡片密码",
                    "constraints": {"allowed_card_ids": [card_id]},
                    "candidates": [],
                }

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    self.assertNotIn(str(card_id), str(messages))
                    self.assertIn("allowed_card_count", str(messages))
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "宣言合法卡片",
                                    "intent": {"kind": "announce_card", "card_id": card_id},
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
                parsed = parse_request(body)

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("announcement must not query client")

                action, _reason = await agent.decide(
                    parsed, storage.apply_decision(parsed.data), unused_query
                )
                self.assertEqual(action, {"kind": "announce_card", "card_id": card_id})

    async def test_announce_card_ids_stay_in_validation_request_only(self) -> None:
        body = request()
        body["prompt"] = {
            "kind": "announce_card",
            "description": "请宣言卡片密码",
            "constraints": {"allowed_card_ids": [40575313, 21239280]},
            "candidates": [],
        }
        parsed = parse_request(body)
        visible = model_visible_prompt(parsed)
        self.assertEqual(visible["constraints"], {"allowed_card_count": 2})
        self.assertEqual(intent_format(parsed)["constraints"], {"allowed_card_count": 2})
        self.assertEqual(
            cast(dict[str, Any], parsed.prompt["constraints"])["allowed_card_ids"],
            [40575313, 21239280],
        )
        self.assertNotIn(
            "40575313", json.dumps({"prompt": visible, "intent_format": intent_format(parsed)})
        )

    async def test_calculate_uses_shared_decimal_tool(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {
                                        "code": "await calculate(operation='subtract', "
                                        "left='8000', right='2700')"
                                    },
                                )
                            ]
                        )
                    self.assertIn("5300", str(messages))
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "计算完成",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("calculation must not query client")

                parsed = parse_request(request())
                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                exchange = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(exchange["payload"]["tool_attempts"][0]["name"], "calculate")

    async def test_own_decklist_tool_reads_pinned_catalog(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {
                                        "code": "deck = await own_decklist()\n"
                                        "deck['main'][0]['card_id']"
                                    },
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择当前合法动作",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                parsed = parse_request(request())
                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                self.assertEqual(calls, 2)
                records = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(records["payload"]["tool_attempts"][0]["name"], "own_decklist")

    async def test_batch_card_lookup_rejects_over_limit(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {"code": "await cards_by_ids(card_ids=list(range(1, 14)))"},
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择当前合法动作",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                parsed = parse_request(request())
                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                self.assertEqual(calls, 2)
                records = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(len(records["payload"]["tool_attempts"]), 1)
                self.assertNotIn("result_bytes", records["payload"]["tool_attempts"][0])

    async def test_pregame_query_loop_finalizes_before_request_budget(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                requests = 0

                async def respond(_messages: list[Any], info: Any) -> ModelResponse:
                    nonlocal requests
                    requests += 1
                    if info.function_tools:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code", {"code": "await card_by_id(card_id=5318639)"}
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择石头",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.model_requests = 4
                settings.limits.finalization_reserve_requests = 2
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )
                body = request()
                body["prompt"] = {
                    "kind": "rock_paper_scissors",
                    "description": "选择石头、剪刀或布",
                    "constraints": {},
                    "candidates": [
                        {"id": "c0", "kind": "rock", "description": "石头"},
                        {"id": "c1", "kind": "scissors", "description": "剪刀"},
                        {"id": "c2", "kind": "paper", "description": "布"},
                    ],
                }
                parsed = parse_request(body)

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                action, _ = await agent.decide(
                    parsed, storage.apply_decision(parsed.data), unused_query
                )
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertEqual(requests, 3)
                attempts = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                self.assertEqual(len(attempts["payload"]["tool_attempts"]), 2)

    async def test_batch_card_lookup_is_one_host_call_with_metrics(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return ModelResponse(
                            [
                                ToolCallPart(
                                    "run_code",
                                    {
                                        "code": "cards = await cards_by_ids(card_ids=[5318639])\n"
                                        "cards[0]['id']"
                                    },
                                )
                            ]
                        )
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择当前合法动作",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 0
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                parsed = parse_request(request())
                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                self.assertEqual(calls, 2)
                exchange = storage.get_records("client-a", "duel-1", kind="model_exchange")[0]
                attempt = exchange["payload"]["tool_attempts"][0]
                self.assertEqual(attempt["name"], "cards_by_ids")
                self.assertEqual(attempt["distinct_card_ids"], 1)
                self.assertGreater(attempt["result_bytes"], 0)

    async def test_first_pregame_turn_has_deck_catalog_and_finalization_guard(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                seen: dict[str, Any] = {}

                async def respond(messages: list[Any], info: Any) -> ModelResponse:
                    user_parts = [
                        part.content
                        for message in messages
                        if isinstance(message, ModelRequest)
                        for part in message.parts
                        if isinstance(part, UserPromptPart)
                    ]
                    assert isinstance(user_parts[-1], str)
                    seen["prompt"] = json.loads(user_parts[-1])
                    seen["functions"] = [tool.name for tool in info.function_tools]
                    seen["outputs"] = [tool.name for tool in info.output_tools]
                    seen["instructions"] = info.instructions
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "选择当前合法动作",
                                    "intent": {"kind": "choice", "candidate_id": "c0"},
                                },
                            )
                        ]
                    )

                settings = load_settings(root, offline=True)
                settings.limits.model_requests = 4
                settings.limits.finalization_reserve_requests = 0
                settings.limits.finalization_reserve_seconds = 20
                agent = DecisionAgent(
                    settings, storage, SkillResources(root), model=FunctionModel(respond)
                )

                async def unused_query(_query: dict[str, object]) -> dict[str, object]:
                    self.fail("test model should not query client")

                parsed = parse_request(request())
                await agent.decide(parsed, storage.apply_decision(parsed.data), unused_query)
                self.assertEqual(seen["prompt"]["own_deck_catalog"]["main"][0]["card_id"], 5318639)
                self.assertEqual(seen["functions"], [])
                self.assertIn("final_result", seen["outputs"])
                self.assertIn("最终化", seen["instructions"])
                traces = storage.get_traces("client-a", "duel-1")
                self.assertTrue(any(event["kind"] == "finalization_guard" for event in traces))
                prompt_trace = next(
                    event for event in traces if event["kind"] == "model_request_started"
                )
                self.assertEqual(len(prompt_trace["payload"]["duel_prompt_sha256"]), 64)

    async def test_first_model_turn_receives_confirmed_state_then_deltas(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                storage.append_record(
                    "client-a",
                    "duel-1",
                    "hand_note_revision",
                    "legacy",
                    {"text": "旧版推断，不再提供给模型"},
                )
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
                self.assertFalse(any("note" in key for key in prompts[0]))

                saved = storage.get_record("client-a", "duel-1", "model_context", "1:1")
                assert saved is not None
                storage.append_record(
                    "client-a",
                    "duel-1",
                    "model_context",
                    "legacy",
                    {"messages": saved["payload"]["messages"]},
                )
                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )

                second_body = request()
                second_body["state_version"] = 2
                second_body["prompt_id"] = 2
                second_body["observation"]["life_points"] = [7500, 8000]
                second = parse_request(second_body)
                second_delta = storage.apply_decision(second.data)
                await agent.decide(second, second_delta, unused_query)
                self.assertEqual(
                    prompts[1]["initial_state"], storage.get_state("client-a", "duel-1", 2)
                )
                self.assertEqual(prompts[1]["net_changes"], list(second_delta.changes))
                self.assertFalse(any("note" in key for key in prompts[1]))
                self.assertEqual(
                    len(storage.get_records("client-a", "duel-1", kind="hand_note_revision")), 1
                )

                agent = DecisionAgent(
                    load_settings(root, offline=True),
                    storage,
                    SkillResources(root),
                    model=FunctionModel(respond),
                )
                third_body = request()
                third_body["state_version"] = 3
                third_body["prompt_id"] = 3
                third = parse_request(third_body)
                third_delta = storage.apply_decision(third.data)
                await agent.decide(third, third_delta, unused_query)
                self.assertNotIn("initial_state", prompts[2])
                self.assertEqual(prompts[2]["net_changes"], list(third_delta.changes))

    async def test_model_can_recall_prior_reveal_without_notes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(messages: list[Any], _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        return ModelResponse(
                            [ToolCallPart("event_history", {"after_event_id": 0, "limit": 10})]
                        )
                    if calls == 3:
                        self.assertIn("89023486", str(messages))
                    return ModelResponse(
                        [
                            ToolCallPart(
                                "final_result",
                                {
                                    "reason": "按已确认历史选择动作",
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

                async def unused_query(_query: dict[str, Any]) -> dict[str, Any]:
                    self.fail("client query was not requested")

                first_body = request()
                first_body["observation"]["events"] = [
                    {
                        "event_id": 1,
                        "kind": "cards_revealed",
                        "message_type": 31,
                        "cards": [{"player": 1, "location": 8, "sequence": 3, "card_id": 89023486}],
                    }
                ]
                first = parse_request(first_body)
                await agent.decide(first, storage.apply_decision(first.data), unused_query)

                second_body = request()
                second_body["state_version"] = 2
                second_body["prompt_id"] = 2
                second = parse_request(second_body)
                delta = storage.apply_decision(second.data)
                self.assertEqual(delta.events, ())
                action, _reason = await agent.decide(second, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertEqual(calls, 3)

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
                assert settings.model is not None
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

    async def test_monty_reads_confirmed_zone_without_client_query(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                calls = 0

                async def respond(_messages: object, _info: object) -> ModelResponse:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        code = "await zone_state(player=0, zone='graveyard')"
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

                async def unused_query(_query: dict[str, Any]) -> dict[str, Any]:
                    self.fail("client query was not requested")

                parsed = parse_request(request())
                delta = storage.apply_decision(parsed.data)
                action, _reason = await agent.decide(parsed, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
