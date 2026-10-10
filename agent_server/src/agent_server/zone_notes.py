"""Perspective-scoped, model-authored notes about hidden-zone knowledge."""

from __future__ import annotations

import uuid
from typing import Any, cast

from agent_sdk.state import StateError

from agent_server.storage import StateDatabase

NOTE_KINDS = {"hand": "hand_note_revision", "spell": "spell_note_revision"}
MAIN_MONSTER_SEQUENCES = range(5)
MAX_NOTE_CHARS = 2000
MAX_EVIDENCE_IDS = 20


def _note_kind(player: int, zone: str, sequence: int | None) -> str:
    if type(player) is not int or player != 1:
        raise StateError("invalid_note", "only opponent notes are writable")
    if zone == "main_monster":
        if type(sequence) is not int or sequence not in MAIN_MONSTER_SEQUENCES:
            raise StateError("invalid_note", "main_monster requires sequence 0 to 4")
        return f"main_monster_note_revision_{sequence}"
    if zone not in NOTE_KINDS or sequence is not None:
        raise StateError("invalid_note", "invalid note zone or sequence")
    return NOTE_KINDS[zone]


class ZoneNotes:
    """Keep Agent inference separate from authoritative observations."""

    def __init__(self, store: StateDatabase) -> None:
        self.store = store

    def current(
        self,
        session: str,
        duel: str,
        ack_event_id: int,
        player: int = 1,
        zone: str = "hand",
        sequence: int | None = None,
    ) -> dict[str, Any]:
        kind = _note_kind(player, zone, sequence)
        record = self.store.get_latest_record(session, duel, kind)
        if record is None:
            result: dict[str, Any] = {
                "status": "unwritten",
                "player": player,
                "zone": zone,
                "note": None,
                "ack_event_id": ack_event_id,
            }
            if sequence is not None:
                result["sequence"] = sequence
            return result
        payload = cast(dict[str, Any], record["payload"])
        result = {
            "status": "agent_inference",
            "player": player,
            "zone": zone,
            "note": payload["text"],
            "revision_id": record["record_id"],
            "created_unix_ms": record["created_unix_ms"],
            "evidence_event_ids": payload["evidence_event_ids"],
            "observed_ack_event_id": payload["observed_ack_event_id"],
            "ack_event_id": ack_event_id,
            "newer_events_exist": ack_event_id > payload["observed_ack_event_id"],
        }
        if sequence is not None:
            result["sequence"] = sequence
        return result

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
        sequence: int | None = None,
    ) -> dict[str, Any]:
        kind = _note_kind(player, zone, sequence)
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
        payload: dict[str, Any] = {
            "player": player,
            "zone": zone,
            "text": note.strip(),
            "evidence_event_ids": evidence_event_ids,
            "observed_ack_event_id": ack_event_id,
            "state_version": state_version,
        }
        if sequence is not None:
            payload["sequence"] = sequence
        self.store.append_record(
            session,
            duel,
            kind,
            revision_id,
            payload,
        )
        return self.current(session, duel, ack_event_id, player, zone, sequence)
