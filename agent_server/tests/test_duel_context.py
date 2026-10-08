"""Durable deck and instruction binding at the first decision."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_sdk.contract import ContractError, parse_request
from agent_sdk.state import StateError
from test_decision_session import request

from agent_server.duel_context import DuelContext
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase

ROOT = Path(__file__).resolve().parents[2]


class DuelContextTests(unittest.TestCase):
    def test_missing_conflict_restart_and_prompt_pin(self) -> None:
        skills = SkillResources(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateDatabase(path) as store:
                context = DuelContext(ROOT, store, skills)
                body = request()
                manifest = body.pop("deck_manifest")
                with self.assertRaises(StateError) as missing:
                    context.ensure(parse_request(body))
                self.assertEqual(missing.exception.code, "deck_manifest_missing")
                body["deck_manifest"] = manifest
                context.ensure(parse_request(body))
                pinned = context.prompt("client-a", "duel-1")
                self.assertEqual(context.deck("client-a", "duel-1"), manifest)
                self.assertEqual(context.catalog("client-a", "duel-1")["main"][0]["count"], 3)
                changed = request()
                changed["deck_manifest"]["main"][0]["count"] = 2
                with self.assertRaises(StateError) as conflict:
                    context.ensure(parse_request(changed))
                self.assertEqual(conflict.exception.code, "deck_manifest_conflict")
            with StateDatabase(path) as restarted_store:
                restarted = DuelContext(ROOT, restarted_store, skills)
                restarted.prompt_text = "new version loaded for future duels"
                without_manifest = request()
                without_manifest.pop("deck_manifest")
                restarted.ensure(parse_request(without_manifest))
                self.assertEqual(restarted.prompt("client-a", "duel-1"), pinned)

    def test_manifest_shape_is_canonical(self) -> None:
        body = request()
        body["deck_manifest"]["main"] = [
            {"card_id": 10, "count": 1},
            {"card_id": 10, "count": 1},
        ]
        with self.assertRaises(ContractError):
            parse_request(body)
        body["deck_manifest"]["main"] = [{"card_id": 10, "count": True}]
        with self.assertRaises(ContractError):
            parse_request(body)
