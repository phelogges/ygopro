"""Pin the local system prompt and submitted deck once per duel."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import DecisionRequest
from agent_sdk.state import StateError

from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


class DuelContext:
    def __init__(self, release_root: Path, store: StateDatabase, skills: SkillResources) -> None:
        self.store = store
        self.skills = skills
        root = release_root.resolve()
        path = root / ".agents" / "prompts" / "duel_system.md"
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("release-local duel system prompt is missing")
        raw = path.read_bytes()
        if not raw or len(raw) > 32768:
            raise ValueError("duel system prompt must contain 1 to 32768 bytes")
        self.prompt_text = raw.decode("utf-8")
        self.prompt_sha256 = hashlib.sha256(raw).hexdigest()

    def ensure(self, request: DecisionRequest) -> None:
        data = request.data
        session, duel = cast(str, data["session_id"]), cast(str, data["duel_id"])
        existing = self.store.get_record(session, duel, "deck_manifest", "submitted")
        incoming = data.get("deck_manifest")
        if existing is None:
            if incoming is None:
                raise StateError("deck_manifest_missing", "first decision requires submitted deck")
            manifest = cast(dict[str, Any], incoming)
            ids = [
                entry["card_id"] for zone in ("main", "extra", "side") for entry in manifest[zone]
            ]
            for card in self.skills.cards_by_ids(sorted(set(ids))):
                if card.get("name") is None:
                    raise StateError("invalid_request", "deck contains unknown card ID")
            self.store.append_record(session, duel, "deck_manifest", "submitted", manifest)
        elif incoming is not None and incoming != existing["payload"]:
            raise StateError("deck_manifest_conflict", "submitted deck differs from pinned deck")
        if self.store.get_record(session, duel, "duel_prompt", "initial") is None:
            self.store.append_record(
                session,
                duel,
                "duel_prompt",
                "initial",
                {"text": self.prompt_text, "sha256": self.prompt_sha256},
            )

    def prompt(self, session: str, duel: str) -> dict[str, str]:
        record = self.store.get_record(session, duel, "duel_prompt", "initial")
        if record is None:
            raise StateError("invalid_storage", "duel prompt is missing")
        payload = cast(dict[str, Any], record["payload"])
        text = payload.get("text")
        digest = payload.get("sha256")
        if not isinstance(text, str) or not isinstance(digest, str):
            raise StateError("invalid_storage", "duel prompt is malformed")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise StateError("invalid_storage", "duel prompt checksum mismatch")
        return {"text": text, "sha256": digest}

    def deck(self, session: str, duel: str) -> dict[str, Any]:
        record = self.store.get_record(session, duel, "deck_manifest", "submitted")
        if record is None:
            raise StateError("deck_manifest_missing", "submitted deck is missing")
        return cast(dict[str, Any], record["payload"])

    def catalog(self, session: str, duel: str) -> dict[str, Any]:
        manifest = self.deck(session, duel)
        ids = sorted({entry["card_id"] for zone in ("main", "extra") for entry in manifest[zone]})
        details = {card["id"]: card for card in self.skills.cards_by_ids(ids)}
        return {
            zone: [
                {
                    "card_id": entry["card_id"],
                    "count": entry["count"],
                    "name": details[entry["card_id"]]["name"],
                    "card_type": details[entry["card_id"]]["card_type"],
                }
                for entry in manifest[zone]
            ]
            for zone in ("main", "extra")
        }
