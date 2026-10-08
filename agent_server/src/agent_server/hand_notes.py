"""Perspective-scoped, model-authored notes about hidden-zone knowledge."""

from __future__ import annotations

import uuid
from typing import Any, cast

from agent_sdk.state import StateError

from agent_server.storage import StateDatabase

NOTE_KIND = "hand_note_revision"
MAX_NOTE_CHARS = 2000
MAX_EVIDENCE_IDS = 20


class HandNotes:
    """Keep inference separate from authoritative observations and event history."""

    def __init__(self, store: StateDatabase) -> None:
        self.store = store

    def current(self, session: str, duel: str, ack_event_id: int) -> dict[str, Any]:
        record = self.store.get_latest_record(session, duel, NOTE_KIND)
        if record is None:
            return {
                "status": "unwritten",
                "player": 1,
                "zone": "hand",
                "note": None,
                "ack_event_id": ack_event_id,
            }
        payload = cast(dict[str, Any], record["payload"])
        return {
            "status": "agent_inference",
            "player": 1,
            "zone": "hand",
            "note": payload["text"],
            "revision_id": record["record_id"],
            "created_unix_ms": record["created_unix_ms"],
            "evidence_event_ids": payload["evidence_event_ids"],
            "observed_ack_event_id": payload["observed_ack_event_id"],
            "ack_event_id": ack_event_id,
            "newer_events_exist": ack_event_id > payload["observed_ack_event_id"],
        }

    def write(
        self,
        session: str,
        duel: str,
        state_version: int,
        ack_event_id: int,
        player: int,
        zone: str,
        note: str,
        evidence_event_ids: list[int],
    ) -> dict[str, Any]:
        if type(player) is not int or player != 1 or zone != "hand":
            raise StateError("invalid_note", "only the opponent hand is writable")
        if type(note) is not str or not 0 < len(note.strip()) <= MAX_NOTE_CHARS:
            raise StateError("invalid_note", "note must contain 1 to 2000 characters")
        if (
            type(evidence_event_ids) is not list
            or not 1 <= len(evidence_event_ids) <= MAX_EVIDENCE_IDS
            or any(type(item) is not int or item < 1 for item in evidence_event_ids)
            or len(set(evidence_event_ids)) != len(evidence_event_ids)
        ):
            raise StateError("invalid_note", "evidence_event_ids must contain 1 to 20 unique IDs")
        for event_id in evidence_event_ids:
            if event_id > ack_event_id:
                raise StateError("invalid_note", "evidence event is newer than this decision")
            observed = self.store.get_events(
                session,
                duel,
                state_version=state_version,
                after_event_id=event_id - 1,
                limit=1,
            )
            if not observed or observed[0]["event_id"] != event_id:
                raise StateError("invalid_note", "evidence event is absent from this view")
        revision_id = f"{state_version}:{uuid.uuid4().hex}"
        self.store.append_record(
            session,
            duel,
            NOTE_KIND,
            revision_id,
            {
                "player": player,
                "zone": zone,
                "text": note.strip(),
                "evidence_event_ids": evidence_event_ids,
                "observed_ack_event_id": ack_event_id,
                "state_version": state_version,
            },
        )
        return self.current(session, duel, ack_event_id)
