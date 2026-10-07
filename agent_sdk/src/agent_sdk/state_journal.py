"""Durable, per-perspective checkpoints for the deterministic state store.

Each accepted operation is applied to a detached candidate store. The candidate
becomes live only after a complete checkpoint has been atomically replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import cast

from .state import JSONObject, StateDelta, StateError, StateStore


def _canonical(data: JSONObject) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _key(data: object) -> tuple[str, str]:
    if not isinstance(data, dict):
        raise StateError("invalid_state", "request must be an object")
    document = cast(dict[str, object], data)
    session, duel = document.get("session_id"), document.get("duel_id")
    if not isinstance(session, str) or not session or not isinstance(duel, str) or not duel:
        raise StateError("invalid_state", "session_id and duel_id must be nonempty strings")
    return session, duel


class StateJournal:
    """StateStore with atomic local checkpoints, scoped to session and duel."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        if self._root.is_symlink():
            raise StateError("invalid_storage", "checkpoint directory must not be a symlink")
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise StateError("invalid_storage", "checkpoint root is not a directory")
        self._stores: dict[tuple[str, str], StateStore] = {}
        self._lock = threading.RLock()

    def _path(self, key: tuple[str, str]) -> Path:
        identity = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._root / f"{hashlib.sha256(identity).hexdigest()}.json"

    def _load(self, key: tuple[str, str]) -> StateStore:
        if key in self._stores:
            return self._stores[key]
        store = StateStore()
        path = self._path(key)
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise StateError("invalid_checkpoint", "checkpoint file must not be a symlink")
            try:
                raw = path.read_bytes()
                wrapper: object = json.loads(raw)
                if not isinstance(wrapper, dict):
                    raise StateError("invalid_checkpoint", "invalid checkpoint envelope")
                parsed = cast(dict[str, object], wrapper)
                if set(parsed) != {"state", "sha256"}:
                    raise StateError("invalid_checkpoint", "invalid checkpoint envelope")
                state = parsed["state"]
                if not isinstance(state, dict) or not isinstance(parsed["sha256"], str):
                    raise StateError("invalid_checkpoint", "invalid checkpoint content")
                digest = hashlib.sha256(_canonical(cast(JSONObject, state))).hexdigest()
                if digest != parsed["sha256"]:
                    raise StateError("invalid_checkpoint", "checkpoint checksum mismatch")
                document = cast(JSONObject, state)
                if (document.get("session_id"), document.get("duel_id")) != key:
                    raise StateError("invalid_checkpoint", "checkpoint identity mismatch")
                store.import_duel(document)
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                if isinstance(exc, StateError):
                    raise
                raise StateError(
                    "invalid_checkpoint", "checkpoint is unreadable or truncated"
                ) from exc
        self._stores[key] = store
        return store

    def _save(self, key: tuple[str, str], store: StateStore) -> None:
        state = store.export_duel(*key)
        wrapper: JSONObject = {
            "state": state,
            "sha256": hashlib.sha256(_canonical(state)).hexdigest(),
        }
        payload = _canonical(wrapper)
        target = self._path(key)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".state-", suffix=".tmp", dir=self._root, delete=False
            ) as stream:
                temporary = stream.name
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            directory_fd = os.open(self._root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise StateError("storage_error", f"cannot save checkpoint: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _candidate(self, key: tuple[str, str]) -> StateStore:
        live = self._load(key)
        candidate = StateStore()
        try:
            candidate.import_duel(live.export_duel(*key))
        except StateError as exc:
            if exc.code != "state_not_found":
                raise
        return candidate

    def apply_sync(self, envelope: object) -> int:
        key = _key(envelope)
        with self._lock:
            candidate = self._candidate(key)
            ack = candidate.apply_sync(envelope)
            try:
                self._save(key, candidate)
            except StateError:
                self._stores.pop(key, None)
                raise
            self._stores[key] = candidate
            return ack

    def apply_decision(self, request: object) -> StateDelta:
        key = _key(request)
        with self._lock:
            candidate = self._candidate(key)
            delta = candidate.apply_decision(request)
            try:
                self._save(key, candidate)
            except StateError:
                self._stores.pop(key, None)
                raise
            self._stores[key] = candidate
            return delta

    def get_state(self, session_id: str, duel_id: str, state_version: int) -> JSONObject:
        with self._lock:
            return self._load((session_id, duel_id)).get_state(session_id, duel_id, state_version)

    def get_status(self, session_id: str, duel_id: str) -> dict[str, int]:
        with self._lock:
            return self._load((session_id, duel_id)).get_status(session_id, duel_id)

    def get_zone(
        self, session_id: str, duel_id: str, state_version: int, player: int, name: str
    ) -> JSONObject:
        with self._lock:
            return self._load((session_id, duel_id)).get_zone(
                session_id, duel_id, state_version, player, name
            )

    def get_events(
        self,
        session_id: str,
        duel_id: str,
        *,
        state_version: int | None = None,
        after_event_id: int = 0,
        limit: int = 100,
    ) -> tuple[JSONObject, ...]:
        with self._lock:
            return self._load((session_id, duel_id)).get_events(
                session_id,
                duel_id,
                state_version=state_version,
                after_event_id=after_event_id,
                limit=limit,
            )
