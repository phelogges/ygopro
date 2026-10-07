"""Local v3 HTTP request chain with separate client and viewer credentials."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from test_decision_session import request

from agent_server.__main__ import offline_decide
from agent_server.config import load_settings
from agent_server.http_service import HttpService
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class HttpServiceTests(unittest.IsolatedAsyncioTestCase):
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
            "/v3/status", data='{"schema_version":3,"x":NaN}',
            headers={**headers, "Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 400)
        response = await self.client.get("/v3/ready", headers=headers)
        self.assertEqual((await response.json())["nonce"], "nonce-1234567890")
        body = request()
        body["database_sha256"] = self.skills.database_sha256
        response = await self.client.post("/v3/decision", json=body, headers=headers)
        self.assertEqual(response.status, 200)
        action = await response.json()
        self.assertEqual(action["kind"], "action")
        self.assertEqual(action["action"], {"kind": "choice", "candidate_id": "c0"})
        response = await self.client.post("/v3/decision", json=body, headers=headers)
        self.assertEqual(await response.json(), action)
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
        self.assertEqual(len((await response.json())["duels"]), 1)
        view_path = "/v3/view/deltas?session_id=client-a&duel_id=duel-1"
        response = await self.client.get(view_path, headers=viewer)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["deltas"][0]["state_version"], 1)
        response = await self.client.get(view_path + "&limit=bad", headers=viewer)
        self.assertEqual(response.status, 400)
        response = await self.client.post("/v3/decision", json=body, headers=viewer)
        self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main()
