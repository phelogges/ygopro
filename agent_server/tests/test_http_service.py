"""Local v3 HTTP request chain with separate client and viewer credentials."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from aiohttp.test_utils import TestClient, TestServer
from test_decision_session import request

from agent_server.__main__ import offline_decide
from agent_server.config import load_settings
from agent_server.http_service import HttpService
from agent_server.model_agent import DecisionFailure
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class HttpServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_error_has_distinct_status_and_code(self) -> None:
        response = HttpService.error(
            DecisionFailure("budget_exhausted", "model or tool budget exhausted")
        )
        self.assertEqual(response.status, 429)
        assert isinstance(response.body, bytes | bytearray)
        self.assertEqual(json.loads(response.body)["error"]["code"], "budget_exhausted")

    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        self.storage = StateDatabase(Path(self.temp.name) / "state.sqlite3")
        self.skills = SkillResources(root)
        service = HttpService(
            load_settings(root, offline=True),
            self.storage,
            self.skills,
            offline_decide,
            profile="config",
            nonce="nonce-1234567890",
            client_token="client-secret",
            viewer_token="viewer-secret",
        )
        self.service = service
        self.client = TestClient(TestServer(service.app()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.storage.close()
        self.temp.cleanup()

    async def test_decision_receipt_status_and_viewer_isolation(self) -> None:
        response = await self.client.get("/v3/ready")
        self.assertEqual(response.status, 401)
        headers = {"Authorization": "Bearer client-secret"}
        response = await self.client.post(
            "/v3/status",
            data='{"schema_version":3,"x":NaN}',
            headers={**headers, "Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 400)
        response = await self.client.get("/v3/ready", headers=headers)
        self.assertEqual((await response.json())["nonce"], "nonce-1234567890")
        body = request()
        body["database_sha256"] = self.skills.database_sha256
        missing = dict(body)
        missing.pop("deck_manifest")
        response = await self.client.post("/v3/decision", json=missing, headers=headers)
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"]["code"], "deck_manifest_missing")
        response = await self.client.post("/v3/decision", json=body, headers=headers)
        self.assertEqual(response.status, 200)
        action = await response.json()
        self.assertEqual(action["kind"], "action")
        self.assertEqual(action["action"], {"kind": "choice", "candidate_id": "c0"})
        response = await self.client.post("/v3/decision", json=body, headers=headers)
        self.assertEqual(await response.json(), action)
        conflicting = request()
        conflicting["database_sha256"] = self.skills.database_sha256
        conflicting["deck_manifest"]["main"][0]["count"] = 2
        response = await self.client.post("/v3/decision", json=conflicting, headers=headers)
        self.assertEqual(response.status, 409)
        self.assertEqual((await response.json())["error"]["code"], "deck_manifest_conflict")
        receipt = {
            **{
                key: action[key]
                for key in (
                    "schema_version",
                    "session_id",
                    "duel_id",
                    "prompt_id",
                    "state_version",
                    "action_id",
                )
            },
            "status": "submitted",
        }
        response = await self.client.post("/v3/action-result", json=receipt, headers=headers)
        self.assertEqual((await response.json())["status"], "acknowledged")
        viewer = {"Authorization": "Bearer viewer-secret"}
        response = await self.client.get("/v3/view/duels", headers=headers)
        self.assertEqual(response.status, 401)
        response = await self.client.get("/v3/view/duels", headers=viewer)
        duels = (await response.json())["duels"]
        self.assertEqual(len(duels), 1)
        self.assertEqual(duels[0]["status"], "unconfirmed")
        self.assertLessEqual(duels[0]["started_unix_ms"], duels[0]["last_activity_unix_ms"])
        view_path = "/v3/view/deltas?session_id=client-a&duel_id=duel-1"
        response = await self.client.get(view_path, headers=viewer)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["deltas"][0]["state_version"], 1)
        response = await self.client.get(view_path + "&limit=bad", headers=viewer)
        self.assertEqual(response.status, 400)
        response = await self.client.post("/v3/decision", json=body, headers=viewer)
        self.assertEqual(response.status, 401)

    async def test_terminal_sync_interrupts_in_flight_model(self) -> None:
        started = asyncio.Event()
        interrupted = asyncio.Event()

        async def slow_decide(
            _request: object, _delta: object, _ask: object
        ) -> tuple[dict[str, Any], str]:
            started.set()
            try:
                await asyncio.Future[None]()
            except asyncio.CancelledError:
                interrupted.set()
                # A tool may swallow cancellation; it still cannot issue an action.
                return {"kind": "choice", "candidate_id": "c0"}, "late result"
            raise AssertionError("in-flight decision must be cancelled")

        self.service.manager.decide = slow_decide
        headers = {"Authorization": "Bearer client-secret"}
        body = request()
        body["database_sha256"] = self.skills.database_sha256
        pending = asyncio.create_task(self.client.post("/v3/decision", json=body, headers=headers))
        await asyncio.wait_for(started.wait(), timeout=2)

        finished = {
            "schema_version": 3,
            "session_id": body["session_id"],
            "duel_id": body["duel_id"],
            "database_sha256": body["database_sha256"],
            "history_complete": True,
            "events": [
                {"event_id": 1, "kind": "duel_ended", "message_type": 5, "winner": 0, "reason": 0}
            ],
        }
        response = await self.client.post("/v3/sync", json=finished, headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["ack_event_id"], 1)
        await asyncio.wait_for(interrupted.wait(), timeout=2)
        stale = await asyncio.wait_for(pending, timeout=2)
        self.assertEqual((await stale.json())["error"]["code"], "stale_prompt")
        duplicate = await self.client.post("/v3/sync", json=finished, headers=headers)
        self.assertEqual(duplicate.status, 200)
        self.assertEqual((await duplicate.json())["ack_event_id"], 1)
        self.assertEqual(
            len(self.storage.get_records("client-a", "duel-1", kind="duel_finished")), 1
        )
        self.assertEqual(self.storage.get_records("client-a", "duel-1", kind="agent_action"), ())
        replay = await self.client.post("/v3/decision", json=body, headers=headers)
        self.assertEqual((await replay.json())["error"]["code"], "stale_prompt")

    async def test_terminal_sync_cancels_pending_client_query(self) -> None:
        async def query_decide(
            _request: object, _delta: object, ask: Any
        ) -> tuple[dict[str, Any], str]:
            await ask({"kind": "inspect_zone", "player": 0, "zone": "graveyard"})
            return {"kind": "choice", "candidate_id": "c0"}, "late result"

        self.service.manager.decide = query_decide
        headers = {"Authorization": "Bearer client-secret"}
        body = request()
        body["database_sha256"] = self.skills.database_sha256
        response = await self.client.post("/v3/decision", json=body, headers=headers)
        query = await response.json()
        self.assertEqual(query["kind"], "query")

        finished = {
            "schema_version": 3,
            "session_id": body["session_id"],
            "duel_id": body["duel_id"],
            "database_sha256": body["database_sha256"],
            "history_complete": True,
            "events": [
                {"event_id": 1, "kind": "duel_ended", "message_type": 5, "winner": 0, "reason": 0}
            ],
        }
        response = await self.client.post("/v3/sync", json=finished, headers=headers)
        self.assertEqual(response.status, 200)
        result: dict[str, Any] = {
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
        late = await self.client.post("/v3/query-result", json=result, headers=headers)
        self.assertEqual((await late.json())["error"]["code"], "query_not_pending")
        self.assertEqual(self.storage.get_records("client-a", "duel-1", kind="agent_action"), ())

    async def test_observation_page_timeline_export_and_sanitized_records(self) -> None:
        viewer = {"Authorization": "Bearer viewer-secret"}
        self.storage.apply_decision(request())
        for path in ("/view", "/view/app.js", "/view/style.css"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
        self.storage.add_trace(
            "client-a",
            "duel-1",
            "4:2",
            "4:2:r1",
            "content_delta",
            {"source": "provider_reasoning", "form": "summary", "text": "检查墓地"},
        )
        self.storage.append_record(
            "client-a",
            "duel-1",
            "model_exchange",
            "4:2",
            {"new_messages": [{"signature": "encrypted-secret"}], "reason": "结束阶段"},
        )
        self.storage.append_record(
            "client-a",
            "duel-1",
            "hand_note_revision",
            "revision-1",
            {
                "player": 1,
                "zone": "hand",
                "text": "对手曾展示旋风，当前是否仍在手牌待核对。",
                "evidence_event_ids": [1],
                "observed_ack_event_id": 1,
                "state_version": 1,
            },
        )
        path = "/v3/view/timeline?session_id=client-a&duel_id=duel-1"
        response = await self.client.get(path, headers=viewer)
        data = await response.json()
        self.assertEqual(data["traces"][0]["payload"]["text"], "检查墓地")
        response = await self.client.get(path + "&after_id=" + str(data["next_id"]), headers=viewer)
        self.assertEqual((await response.json())["traces"], [])
        response = await self.client.get("/v3/view/cards?ids=89631139", headers=viewer)
        self.assertEqual((await response.json())["cards"]["89631139"], "青眼白龙")
        response = await self.client.get(
            "/v3/view/export?session_id=client-a&duel_id=duel-1", headers=viewer
        )
        exported = await response.text()
        self.assertIn("检查墓地", exported)
        self.assertNotIn("encrypted-secret", exported)
        missing = await self.client.get(
            "/v3/view/export?session_id=client-a&duel_id=missing", headers=viewer
        )
        self.assertEqual(missing.status, 404)
        response = await self.client.get(
            "/v3/view/records?session_id=client-a&duel_id=duel-1", headers=viewer
        )
        self.assertNotIn("encrypted-secret", await response.text())
        response = await self.client.get(
            "/v3/view/records?session_id=client-a&duel_id=duel-1&kind=hand_note_revision",
            headers=viewer,
        )
        self.assertEqual(response.status, 200)
        notes = (await response.json())["records"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["payload"]["evidence_event_ids"], [1])
        response = await self.client.get(
            "/v3/view/records?session_id=client-a&duel_id=duel-1&kind=model_context",
            headers=viewer,
        )
        self.assertEqual(response.status, 400)

    async def test_view_only_excludes_client_routes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        service = HttpService(
            load_settings(root, offline=True),
            self.storage,
            self.skills,
            offline_decide,
            profile="config",
            nonce="",
            client_token="",
            viewer_token="viewer-secret",
            view_only=True,
        )
        client = TestClient(TestServer(service.app()))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/v3/ready")).status, 404)
            self.assertEqual((await client.post("/v3/decision")).status, 404)
            self.assertEqual((await client.get("/v3/view/duels")).status, 401)
        finally:
            await client.close()

    async def test_stream_replays_from_exclusive_cursor(self) -> None:
        self.storage.apply_decision(request())
        first = self.storage.add_trace("client-a", "duel-1", "1:1", None, "prompt_received", {})
        second = self.storage.add_trace(
            "client-a", "duel-1", "1:1", None, "model_request_started", {}
        )
        viewer = {"Authorization": "Bearer viewer-secret"}
        response = await self.client.get(
            f"/v3/view/stream?session_id=client-a&duel_id=duel-1&after_id={first}",
            headers=viewer,
        )
        try:
            self.assertEqual(response.status, 200)
            event_id = await asyncio.wait_for(response.content.readline(), timeout=2)
            event_type = await asyncio.wait_for(response.content.readline(), timeout=2)
            body = await asyncio.wait_for(response.content.readline(), timeout=2)
            self.assertEqual(event_id, f"id: {second}\n".encode())
            self.assertEqual(event_type, b"event: trace\n")
            self.assertEqual(json.loads(body.removeprefix(b"data: "))["id"], second)
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
