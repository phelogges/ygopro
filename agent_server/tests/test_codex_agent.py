"""Offline Codex SDK turn integration and semantic-action validation."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_sdk.contract import parse_request
from test_decision_session import request

from agent_server.codex_agent import CodexDecisionAgent, codex_settings, decision_output_schema
from agent_server.config import load_settings
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase
from agent_server.trace import TraceWriter


class FakeBridge:
    def __init__(self) -> None:
        self.active = False

    def mcp_config(self) -> dict[str, Any]:
        return {"command": "/fake/mcp", "args": ["--stdio"], "env": {"TOKEN": "fixture"}}

    def activate(self, _deps: Any, _context: Any) -> None:
        assert not self.active
        self.active = True

    def deactivate(self) -> None:
        self.active = False


class FakeHandle:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.interrupted = False

    async def stream(self) -> Any:
        yield SimpleNamespace(
            method="item/reasoning/summaryTextDelta", payload={"delta": "检查合法候选。"}
        )
        yield SimpleNamespace(
            method="item/completed",
            payload={"item": {"type": "agentMessage", "phase": "finalAnswer", "text": self.answer}},
        )
        yield SimpleNamespace(method="turn/completed", payload={"turn": {"status": "completed"}})

    async def interrupt(self) -> None:
        self.interrupted = True


class BlockingHandle(FakeHandle):
    def __init__(self) -> None:
        super().__init__("")
        self.started = asyncio.Event()

    async def stream(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        yield SimpleNamespace(method="turn/completed", payload={"turn": {"status": "completed"}})


class FakeThread:
    def __init__(self, answers: list[str]) -> None:
        self.id = "thread-fixture"
        self.answers = answers
        self.inputs: list[list[Any]] = []

    async def turn(self, inputs: list[Any], **_options: Any) -> FakeHandle:
        self.inputs.append(inputs)
        return FakeHandle(self.answers.pop(0))


class FakeCodex:
    def __init__(self, answers: list[str]) -> None:
        self.thread = FakeThread(answers)
        self.start_count = 0

    async def thread_start(self, **_options: Any) -> FakeThread:
        self.start_count += 1
        return self.thread


class CodexAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_announce_card_prompt_omits_allowed_ids(self) -> None:
        root = Path(__file__).resolve().parents[2]
        (root / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "out") as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                card_id = 987654321
                body = request()
                body["prompt"] = {
                    "kind": "announce_card",
                    "description": "请宣言卡片密码",
                    "constraints": {"allowed_card_ids": [card_id]},
                    "candidates": [],
                }
                settings = load_settings(root, offline=True)
                settings.backend = "codex"
                settings.model = None
                fake = FakeCodex(
                    [
                        json.dumps(
                            {
                                "reason": "宣言合法卡片",
                                "intent": {"kind": "announce_card", "card_id": card_id},
                            }
                        )
                    ]
                )
                agent = CodexDecisionAgent(settings, storage, SkillResources(root), Path(directory))
                agent.codex = fake
                agent.bridge = FakeBridge()  # type: ignore[assignment]
                parsed = parse_request(body)

                async def unused_query(_query: dict[str, Any]) -> dict[str, Any]:
                    self.fail("announcement must not query client")

                action, _reason = await agent.decide(
                    parsed, storage.apply_decision(parsed.data), unused_query
                )
                self.assertEqual(action, {"kind": "announce_card", "card_id": card_id})
                model_prompt = json.loads(fake.thread.inputs[0][0].text)
                self.assertEqual(model_prompt["prompt"]["constraints"], {"allowed_card_count": 1})
                self.assertNotIn(str(card_id), fake.thread.inputs[0][0].text)

    async def test_invalid_intent_retries_and_stores_validated_action(self) -> None:
        root = Path(__file__).resolve().parents[2]
        (root / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "out") as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                settings = load_settings(root, offline=True)
                settings.backend = "codex"
                settings.model = None
                answers = [
                    json.dumps(
                        {"reason": "测试", "intent": {"kind": "choice", "candidate_id": "bad"}}
                    ),
                    json.dumps(
                        {
                            "reason": "选择合法动作",
                            "intent": {"kind": "choice", "candidate_id": "c0"},
                        }
                    ),
                ]
                fake = FakeCodex(answers)
                agent = CodexDecisionAgent(settings, storage, SkillResources(root), Path(directory))
                agent.codex = fake
                agent.bridge = FakeBridge()  # type: ignore[assignment]
                storage.append_record(
                    "client-a", "duel-1", "codex_thread", "initial", {"thread_id": "old-thread"}
                )
                storage.append_record(
                    "client-a", "duel-1", "model_exchange", "legacy", {"backend": "codex"}
                )
                parsed = parse_request(request())
                delta = storage.apply_decision(parsed.data)

                async def unused_query(_query: dict[str, Any]) -> dict[str, Any]:
                    self.fail("Codex fixture must not query client")

                action, reason = await agent.decide(parsed, delta, unused_query)
                self.assertEqual(action, {"kind": "choice", "candidate_id": "c0"})
                self.assertEqual(reason, "选择合法动作")
                self.assertEqual(fake.start_count, 1)
                self.assertEqual(len(fake.thread.inputs), 2)
                self.assertEqual(len(fake.thread.inputs[0]), 3)  # state plus two explicit skills
                self.assertEqual(len(fake.thread.inputs[1]), 1)
                self.assertIn("initial_state", json.loads(fake.thread.inputs[0][0].text))
                self.assertFalse(
                    any("note" in key for key in json.loads(fake.thread.inputs[0][0].text))
                )
                record = storage.get_record("client-a", "duel-1", "codex_thread", "toolset-v4")
                self.assertEqual(record["payload"]["thread_id"], "thread-fixture")  # type: ignore[index]
                self.assertEqual(record["payload"]["toolset_version"], 4)  # type: ignore[index]
                exchange = storage.get_record("client-a", "duel-1", "model_exchange", "1:1")
                self.assertEqual(exchange["payload"]["backend"], "codex")  # type: ignore[index]

    def test_config_forces_only_local_duel_capabilities(self) -> None:
        bridge = FakeBridge()
        config = codex_settings(Path("/tmp/home"), Path("/tmp/workspace"), bridge)  # type: ignore[arg-type]
        self.assertEqual(config.env["CODEX_HOME"], "/tmp/home")  # type: ignore[index]
        self.assertEqual(config.env["HOME"], "/tmp/home")  # type: ignore[index]
        self.assertEqual(config.env["CODEX_API_KEY"], "")  # type: ignore[index]
        self.assertIn("features.shell_tool=false", config.config_overrides)
        self.assertIn("agents.enabled=false", config.config_overrides)
        self.assertTrue(
            any(value.startswith("mcp_servers.ygopro_duel.") for value in config.config_overrides)
        )

    def test_output_schema_is_closed_and_prompt_specific(self) -> None:
        schema = decision_output_schema(parse_request(request()))
        self.assertIs(schema["additionalProperties"], False)
        intent = schema["properties"]["intent"]
        self.assertIs(intent["additionalProperties"], False)
        self.assertEqual(intent["properties"]["kind"]["enum"], ["choice"])
        self.assertEqual(intent["required"], ["kind", "candidate_id"])

    async def test_cancelled_turn_interrupts_sdk_handle(self) -> None:
        root = Path(__file__).resolve().parents[2]
        (root / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "out") as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                settings = load_settings(root, offline=True)
                settings.backend = "codex"
                settings.model = None
                agent = CodexDecisionAgent(settings, storage, SkillResources(root), Path(directory))
                handle = BlockingHandle()

                class BlockingThread:
                    async def turn(self, _inputs: Any, **_kwargs: Any) -> BlockingHandle:
                        return handle

                trace = TraceWriter(storage, "client-a", "duel-1", "1:1")
                task = asyncio.create_task(
                    agent._run_turn(  # pyright: ignore[reportPrivateUsage]
                        BlockingThread(),
                        "fixture",
                        False,
                        trace,
                        ("client-a", "duel-1"),
                        decision_output_schema(parse_request(request())),
                    )
                )
                await handle.started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(handle.interrupted)


if __name__ == "__main__":
    unittest.main()
