"""Durable, perspective-scoped observations for the local Agent service.

SQLite is the source of truth. StateStore validates every observation and
computes deltas; an acknowledgment is returned only after the matching WAL
transaction commits. Periodic checkpoints bound restart replay without
rewriting the complete duel on every request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import cast

from agent_sdk.state import JSONObject, StateDelta, StateError, StateStore


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise StateError("invalid_state", "value must contain finite JSON data") from exc


def _identity(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise StateError("invalid_state", "request must be an object")
    document = cast(dict[str, object], value)
    session, duel = document.get("session_id"), document.get("duel_id")
    if not isinstance(session, str) or not session or not isinstance(duel, str) or not duel:
        raise StateError("invalid_state", "session_id and duel_id must be nonempty strings")
    return session, duel


def _json_object(raw: bytes | str, *, source: str) -> JSONObject:
    try:
        decoded: object = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise StateError("invalid_storage", f"{source} contains invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise StateError("invalid_storage", f"{source} must contain a JSON object")
    parsed = cast(dict[object, object], decoded)
    if any(not isinstance(key, str) for key in parsed):
        raise StateError("invalid_storage", f"{source} must contain a JSON object")
    return cast(JSONObject, decoded)


class StateDatabase:
    """Append-only observations and auxiliary records for one local service.

    ``path`` is the SQLite file, not a directory. The service owns the file;
    concurrent writers from another process are outside the supported process
    topology. Every public method is safe to call across threads in this
    process. Call ``close`` before replacing or removing the file.
    """

    def __init__(
        self, path: str | Path, *, checkpoint_interval: int = 32, read_only: bool = False
    ) -> None:
        if type(checkpoint_interval) is not int or checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be a positive integer")
        self.path = Path(path)
        if self.path.is_symlink():
            raise StateError("invalid_storage", "database file must not be a symlink")
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.path.parent.is_dir():
            raise StateError("invalid_storage", "database parent is not a directory")
        self._checkpoint_interval = checkpoint_interval
        self._lock = threading.RLock()
        self._stores: dict[tuple[str, str], StateStore] = {}
        try:
            source = self.path.resolve().as_uri() + "?mode=ro" if read_only else self.path
            self._db = sqlite3.connect(
                source, isolation_level=None, check_same_thread=False, uri=read_only
            )
            self._db.row_factory = sqlite3.Row
            if not read_only:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA busy_timeout=5000")
            if read_only:
                self._verify_schema()
            else:
                self._initialize()
            self._data_version = cast(int, self._db.execute("PRAGMA data_version").fetchone()[0])
            if not read_only and os.name == "posix":
                os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error) as exc:
            raise StateError("storage_error", f"cannot open state database: {exc}") from exc

    def __enter__(self) -> StateDatabase:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _initialize(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                duel_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('sync', 'decision')),
                payload BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                ack_event_id INTEGER NOT NULL,
                delta BLOB,
                created_unix_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS operations_duel
                ON operations(session_id, duel_id, id);
            CREATE TABLE IF NOT EXISTS checkpoints (
                session_id TEXT NOT NULL,
                duel_id TEXT NOT NULL,
                operation_id INTEGER NOT NULL,
                payload BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY (session_id, duel_id)
            );
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                duel_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                record_id TEXT NOT NULL,
                payload BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                created_unix_ms INTEGER NOT NULL,
                UNIQUE (session_id, duel_id, kind, record_id)
            );
            CREATE INDEX IF NOT EXISTS records_duel
                ON records(session_id, duel_id, id);
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                duel_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                response_id TEXT,
                kind TEXT NOT NULL,
                payload BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                created_unix_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS traces_duel
                ON traces(session_id, duel_id, id);
            CREATE INDEX IF NOT EXISTS traces_finished
                ON traces(kind, created_unix_ms);
            """
        )
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise StateError("invalid_storage", "unsupported state database schema")
        if version < 2:
            self._db.execute("PRAGMA user_version=2")

    def _verify_schema(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2):
            raise StateError("invalid_storage", "unsupported state database schema")
        required = {"operations", "checkpoints", "records"}
        if version == 2:
            required.add("traces")
        available = {
            row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not required.issubset(available):
            raise StateError("invalid_storage", "state database schema is incomplete")

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise StateError("read_only", "state database is read-only")

    def _load(self, key: tuple[str, str]) -> StateStore:
        if self.read_only:
            current_version = cast(int, self._db.execute("PRAGMA data_version").fetchone()[0])
            if current_version != self._data_version:
                self._stores.clear()
                self._data_version = current_version
        cached = self._stores.get(key)
        if cached is not None:
            return cached
        session, duel = key
        store = StateStore()
        checkpoint = self._db.execute(
            "SELECT operation_id, payload, sha256 FROM checkpoints "
            "WHERE session_id=? AND duel_id=?",
            key,
        ).fetchone()
        since_id = 0
        if checkpoint is not None:
            payload = cast(bytes, checkpoint["payload"])
            if hashlib.sha256(payload).hexdigest() != checkpoint["sha256"]:
                raise StateError("invalid_storage", "checkpoint checksum mismatch")
            document = _json_object(payload, source="checkpoint")
            if (document.get("session_id"), document.get("duel_id")) != key:
                raise StateError("invalid_storage", "checkpoint identity mismatch")
            try:
                store.import_duel(document)
            except StateError as exc:
                raise StateError("invalid_storage", f"invalid checkpoint: {exc}") from exc
            since_id = cast(int, checkpoint["operation_id"])
            boundary = self._db.execute(
                "SELECT state_version, ack_event_id FROM operations "
                "WHERE id=? AND session_id=? AND duel_id=?",
                (since_id, session, duel),
            ).fetchone()
            if boundary is None or store.get_status(*key) != {
                "state_version": boundary["state_version"],
                "ack_event_id": boundary["ack_event_id"],
            }:
                raise StateError("invalid_storage", "checkpoint boundary mismatch")
        rows = self._db.execute(
            "SELECT kind, payload, sha256, state_version, ack_event_id, delta "
            "FROM operations WHERE session_id=? AND duel_id=? AND id>? ORDER BY id",
            (session, duel, since_id),
        )
        for row in rows:
            payload = cast(bytes, row["payload"])
            if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise StateError("invalid_storage", "observation log checksum mismatch")
            document = _json_object(payload, source="observation log")
            if (document.get("session_id"), document.get("duel_id")) != key:
                raise StateError("invalid_storage", "observation log identity mismatch")
            try:
                if row["kind"] == "sync":
                    ack = store.apply_sync(document)
                    delta = None
                elif row["kind"] == "decision":
                    delta = store.apply_decision(document)
                    ack = delta.ack_event_id
                else:
                    raise StateError("invalid_storage", "unknown observation operation")
            except StateError as exc:
                raise StateError("invalid_storage", f"invalid observation log: {exc}") from exc
            status = store.get_status(*key)
            if (
                status
                != {
                    "state_version": row["state_version"],
                    "ack_event_id": row["ack_event_id"],
                }
                or ack != row["ack_event_id"]
            ):
                raise StateError("invalid_storage", "observation log status mismatch")
            if delta is not None and row["delta"] != _json_bytes(_delta_dict(delta)):
                raise StateError("invalid_storage", "observation log delta mismatch")
        self._stores[key] = store
        return store

    def _apply(self, kind: str, document: object) -> int | StateDelta:
        self._ensure_writable()
        key = _identity(document)
        payload = _json_bytes(document)
        with self._lock:
            store = self._load(key)
            before = store.get_status(*key)
            try:
                self._db.execute("BEGIN IMMEDIATE")
                if kind == "sync":
                    result: int | StateDelta = store.apply_sync(document)
                else:
                    result = store.apply_decision(document)
                after = store.get_status(*key)
                if after == before:
                    self._db.execute("COMMIT")
                    return result
                delta = _json_bytes(_delta_dict(result)) if isinstance(result, StateDelta) else None
                cursor = self._db.execute(
                    "INSERT INTO operations(session_id,duel_id,kind,payload,sha256,"
                    "state_version,ack_event_id,delta,created_unix_ms) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        *key,
                        kind,
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        after["state_version"],
                        after["ack_event_id"],
                        delta,
                        int(time.time() * 1000),
                    ),
                )
                operation_id = cast(int, cursor.lastrowid)
                since = self._db.execute(
                    "SELECT operation_id FROM checkpoints WHERE session_id=? AND duel_id=?",
                    key,
                ).fetchone()
                last_checkpoint = cast(int, since[0]) if since is not None else 0
                count = self._db.execute(
                    "SELECT count(*) FROM operations WHERE session_id=? AND duel_id=? AND id>?",
                    (*key, last_checkpoint),
                ).fetchone()[0]
                if count >= self._checkpoint_interval:
                    checkpoint = _json_bytes(store.export_duel(*key))
                    self._db.execute(
                        "INSERT INTO checkpoints(session_id,duel_id,operation_id,payload,sha256) "
                        "VALUES(?,?,?,?,?) ON CONFLICT(session_id,duel_id) DO UPDATE SET "
                        "operation_id=excluded.operation_id,payload=excluded.payload,"
                        "sha256=excluded.sha256",
                        (*key, operation_id, checkpoint, hashlib.sha256(checkpoint).hexdigest()),
                    )
                self._db.execute("COMMIT")
                return result
            except (sqlite3.Error, StateError, OSError) as exc:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                # A failed transaction may have mutated StateStore in memory.
                self._stores.pop(key, None)
                if isinstance(exc, StateError):
                    raise
                raise StateError("storage_error", f"cannot commit observation: {exc}") from exc

    def apply_sync(self, envelope: object) -> int:
        """Persist a contiguous event suffix before acknowledging it."""
        result = self._apply("sync", envelope)
        assert isinstance(result, int)
        return result

    def apply_decision(self, request: object) -> StateDelta:
        """Persist and diff a versioned snapshot before returning its delta."""
        result = self._apply("decision", request)
        assert isinstance(result, StateDelta)
        return result

    def get_status(self, session_id: str, duel_id: str) -> dict[str, int]:
        with self._lock:
            return self._load((session_id, duel_id)).get_status(session_id, duel_id)

    def last_observation_unix_ms(self, session_id: str, duel_id: str) -> int | None:
        """Return when the latest authoritative observation was durably accepted."""
        with self._lock:
            row = self._db.execute(
                "SELECT MAX(created_unix_ms) FROM operations WHERE session_id=? AND duel_id=?",
                (session_id, duel_id),
            ).fetchone()
            return cast(int | None, row[0])

    def list_duels(self) -> tuple[JSONObject, ...]:
        """List observed duels, including duels with only synced events."""
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id, duel_id, MIN(created_unix_ms) AS started_unix_ms, "
                "MAX(created_unix_ms) AS last_operation_unix_ms "
                "FROM operations GROUP BY session_id, duel_id "
            )
            trace_times: dict[tuple[str, str], tuple[int, int, int | None]] = {}
            if self._db.execute("PRAGMA user_version").fetchone()[0] >= 2:
                for trace in self._db.execute(
                    "SELECT session_id, duel_id, MIN(created_unix_ms) AS first_ms, "
                    "MAX(created_unix_ms) AS last_ms, "
                    "MAX(CASE WHEN kind='duel_finished' THEN created_unix_ms END) AS finished_ms "
                    "FROM traces GROUP BY session_id, duel_id"
                ):
                    trace_times[(trace["session_id"], trace["duel_id"])] = (
                        trace["first_ms"],
                        trace["last_ms"],
                        trace["finished_ms"],
                    )
            duels: list[JSONObject] = []
            for row in rows:
                session_id = cast(str, row["session_id"])
                duel_id = cast(str, row["duel_id"])
                status = self._load((session_id, duel_id)).get_status(session_id, duel_id)
                started = cast(int, row["started_unix_ms"])
                recent = cast(int, row["last_operation_unix_ms"])
                trace_time = trace_times.get((session_id, duel_id))
                finished: int | None = None
                if trace_time is not None:
                    first_trace, last_trace, finished = trace_time
                    started = min(started, first_trace)
                    recent = max(recent, last_trace)
                duels.append(
                    {
                        "session_id": session_id,
                        "duel_id": duel_id,
                        **status,
                        "started_unix_ms": started,
                        "last_activity_unix_ms": recent,
                        "status": "finished" if finished is not None else "unconfirmed",
                    }
                )
            duels.sort(
                key=lambda duel: (
                    -cast(int, duel["last_activity_unix_ms"]),
                    cast(str, duel["session_id"]),
                    cast(str, duel["duel_id"]),
                )
            )
            return tuple(duels)

    def get_state(self, session_id: str, duel_id: str, state_version: int) -> JSONObject:
        with self._lock:
            return self._load((session_id, duel_id)).get_state(session_id, duel_id, state_version)

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

    def get_delta(self, session_id: str, duel_id: str, state_version: int) -> StateDelta:
        """Return one validated net snapshot difference at an exact version."""
        if type(state_version) is not int or state_version < 1:
            raise StateError("invalid_state", "state_version must be a positive integer")
        with self._lock:
            document = self._load((session_id, duel_id)).export_duel(session_id, duel_id)
            records = cast(list[JSONObject], document["records"])
            if state_version > len(records):
                raise StateError("state_not_found", "requested state version is unavailable")
            return _delta_from_record(records[state_version - 1])

    def get_deltas(
        self,
        session_id: str,
        duel_id: str,
        *,
        after_version: int = 0,
        limit: int = 100,
    ) -> tuple[StateDelta, ...]:
        """Page through validated net differences in state-version order."""
        if type(after_version) is not int or after_version < 0:
            raise StateError("invalid_state", "after_version must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise StateError("invalid_state", "limit must be between 1 and 1000")
        with self._lock:
            document = self._load((session_id, duel_id)).export_duel(session_id, duel_id)
            records = cast(list[JSONObject], document["records"])
            return tuple(
                _delta_from_record(record)
                for record in records[after_version : after_version + limit]
            )

    def append_record(
        self, session_id: str, duel_id: str, kind: str, record_id: object, payload: object
    ) -> int:
        """Persist a non-authoritative fact, idempotently by ``kind`` and ID.

        Records do not advance the snapshot version or event acknowledgment.
        The caller validates the shape and perspective of query results and
        action receipts before recording them here.
        """
        self._ensure_writable()
        _identity({"session_id": session_id, "duel_id": duel_id})
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
            raise StateError("invalid_state", "record kind is invalid")
        if not isinstance(record_id, str) or not 0 < len(record_id) <= 256:
            raise StateError("invalid_state", "record ID is invalid")
        if not isinstance(payload, dict):
            raise StateError("invalid_state", "record payload must be an object")
        parsed_payload = cast(dict[object, object], payload)
        if any(not isinstance(key, str) for key in parsed_payload):
            raise StateError("invalid_state", "record payload keys must be strings")
        encoded = _json_bytes(parsed_payload)
        digest = hashlib.sha256(encoded).hexdigest()
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing = self._db.execute(
                    "SELECT id, sha256 FROM records WHERE session_id=? AND duel_id=? "
                    "AND kind=? AND record_id=?",
                    (session_id, duel_id, kind, record_id),
                ).fetchone()
                if existing is not None:
                    if existing["sha256"] != digest:
                        raise StateError("record_conflict", "record ID has different content")
                    self._db.execute("COMMIT")
                    return cast(int, existing["id"])
                cursor = self._db.execute(
                    "INSERT INTO records(session_id,duel_id,kind,record_id,payload,sha256,"
                    "created_unix_ms) VALUES(?,?,?,?,?,?,?)",
                    (
                        session_id,
                        duel_id,
                        kind,
                        record_id,
                        encoded,
                        digest,
                        int(time.time() * 1000),
                    ),
                )
                self._db.execute("COMMIT")
                return cast(int, cursor.lastrowid)
            except (sqlite3.Error, StateError) as exc:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                if isinstance(exc, StateError):
                    raise
                raise StateError("storage_error", f"cannot commit record: {exc}") from exc

    def get_records(
        self,
        session_id: str,
        duel_id: str,
        *,
        after_id: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[JSONObject, ...]:
        """Page through auxiliary records in insertion order."""
        if type(after_id) is not int or after_id < 0:
            raise StateError("invalid_state", "after_id must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise StateError("invalid_state", "limit must be between 1 and 1000")
        with self._lock:
            if kind is None:
                rows = self._db.execute(
                    "SELECT id,kind,record_id,payload,sha256,created_unix_ms FROM records "
                    "WHERE session_id=? AND duel_id=? AND id>? ORDER BY id LIMIT ?",
                    (session_id, duel_id, after_id, limit),
                )
            else:
                rows = self._db.execute(
                    "SELECT id,kind,record_id,payload,sha256,created_unix_ms FROM records "
                    "WHERE session_id=? AND duel_id=? AND id>? AND kind=? ORDER BY id LIMIT ?",
                    (session_id, duel_id, after_id, kind, limit),
                )
            records: list[JSONObject] = []
            for row in rows:
                payload = cast(bytes, row["payload"])
                if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                    raise StateError("invalid_storage", "record checksum mismatch")
                records.append(
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "record_id": row["record_id"],
                        "payload": _json_object(payload, source="record"),
                        "created_unix_ms": row["created_unix_ms"],
                    }
                )
            return tuple(records)

    def get_record(
        self, session_id: str, duel_id: str, kind: str, record_id: str
    ) -> JSONObject | None:
        """Read one auxiliary record by its durable idempotency key."""
        with self._lock:
            row = self._db.execute(
                "SELECT id,kind,record_id,payload,sha256,created_unix_ms FROM records "
                "WHERE session_id=? AND duel_id=? AND kind=? AND record_id=?",
                (session_id, duel_id, kind, record_id),
            ).fetchone()
            if row is None:
                return None
            payload = cast(bytes, row["payload"])
            if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise StateError("invalid_storage", "record checksum mismatch")
            return {
                "id": row["id"],
                "kind": row["kind"],
                "record_id": row["record_id"],
                "payload": _json_object(payload, source="record"),
                "created_unix_ms": row["created_unix_ms"],
            }

    def add_trace(
        self,
        session: str,
        duel: str,
        turn_id: str,
        response_id: str | None,
        kind: str,
        payload: dict[str, object],
    ) -> int:
        """Append one observable step and return its monotonic event ID."""
        self._ensure_writable()
        _identity({"session_id": session, "duel_id": duel})
        if not isinstance(cast(object, turn_id), str) or len(turn_id) > 256:
            raise StateError("invalid_state", "trace turn ID is invalid")
        if response_id is not None and (
            not isinstance(cast(object, response_id), str) or not 0 < len(response_id) <= 256
        ):
            raise StateError("invalid_state", "trace response ID is invalid")
        if not isinstance(cast(object, kind), str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", kind
        ):
            raise StateError("invalid_state", "trace kind is invalid")
        if not isinstance(cast(object, payload), dict) or any(
            not isinstance(cast(object, key), str) for key in payload
        ):
            raise StateError("invalid_state", "trace payload must be a JSON object")
        encoded = _json_bytes(payload)
        with self._lock:
            try:
                cursor = self._db.execute(
                    "INSERT INTO traces(session_id,duel_id,turn_id,response_id,kind,payload,"
                    "sha256,created_unix_ms) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        session,
                        duel,
                        turn_id,
                        response_id,
                        kind,
                        encoded,
                        hashlib.sha256(encoded).hexdigest(),
                        int(time.time() * 1000),
                    ),
                )
                return cast(int, cursor.lastrowid)
            except sqlite3.Error as exc:
                raise StateError("storage_error", f"cannot commit trace: {exc}") from exc

    def get_traces(
        self, session: str, duel: str, after_id: int = 0, limit: int = 100
    ) -> tuple[JSONObject, ...]:
        """Page through one perspective's trace, in insertion order."""
        _identity({"session_id": session, "duel_id": duel})
        if type(after_id) is not int or after_id < 0:
            raise StateError("invalid_state", "after_id must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise StateError("invalid_state", "limit must be between 1 and 1000")
        if self.read_only and self._db.execute("PRAGMA user_version").fetchone()[0] == 1:
            return ()
        with self._lock:
            rows = self._db.execute(
                "SELECT id,turn_id,response_id,kind,payload,sha256,created_unix_ms "
                "FROM traces WHERE session_id=? AND duel_id=? AND id>? ORDER BY id LIMIT ?",
                (session, duel, after_id, limit),
            )
            result: list[JSONObject] = []
            for row in rows:
                encoded = cast(bytes, row["payload"])
                if hashlib.sha256(encoded).hexdigest() != row["sha256"]:
                    raise StateError("invalid_storage", "trace checksum mismatch")
                result.append(
                    {
                        "id": row["id"],
                        "turn_id": row["turn_id"],
                        "response_id": row["response_id"],
                        "kind": row["kind"],
                        "payload": _json_object(encoded, source="trace"),
                        "created_unix_ms": row["created_unix_ms"],
                    }
                )
            return tuple(result)

    def delete_duel(self, session: str, duel: str) -> bool:
        """Delete one duel and its cached state atomically."""
        self._ensure_writable()
        _identity({"session_id": session, "duel_id": duel})
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                removed = False
                for table in ("operations", "checkpoints", "records", "traces"):
                    cursor = self._db.execute(
                        f"DELETE FROM {table} WHERE session_id=? AND duel_id=?", (session, duel)
                    )
                    removed |= cursor.rowcount > 0
                self._db.execute("COMMIT")
                self._stores.pop((session, duel), None)
                return removed
            except sqlite3.Error as exc:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise StateError("storage_error", f"cannot delete duel: {exc}") from exc

    def prune_finished(self, retention_days: int, max_bytes: int) -> int:
        """Prune old finished duels, then oldest finished duels above size limit.

        Size is the logical payload byte count across all four tables. Active
        duels are never deleted, even when they alone exceed the configured cap.
        """
        self._ensure_writable()
        if type(retention_days) is not int or retention_days < 1:
            raise ValueError("retention_days must be positive")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        threshold = int(time.time() * 1000) - retention_days * 86_400_000
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id, duel_id, MAX(created_unix_ms) AS finished_ms "
                "FROM traces WHERE kind='duel_finished' GROUP BY session_id, duel_id "
                "ORDER BY finished_ms, session_id, duel_id"
            ).fetchall()
            removed = 0
            for row in rows:
                if row["finished_ms"] < threshold:
                    removed += int(self.delete_duel(row["session_id"], row["duel_id"]))
            size = self._payload_bytes()
            for row in rows:
                if size <= max_bytes:
                    break
                if row["finished_ms"] >= threshold and self.delete_duel(
                    row["session_id"], row["duel_id"]
                ):
                    removed += 1
                    size = self._payload_bytes()
            return removed

    def mark_interrupted_turns(self) -> int:
        """Close durable prompt traces left without a terminal decision stage."""
        self._ensure_writable()
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id,duel_id,turn_id FROM traces WHERE turn_id<>'' "
                "GROUP BY session_id,duel_id,turn_id HAVING "
                "SUM(CASE WHEN kind IN ('decision_failed','decision_interrupted',"
                "'action_receipt') THEN 1 ELSE 0 END)=0"
            ).fetchall()
            for row in rows:
                self.add_trace(
                    row["session_id"],
                    row["duel_id"],
                    row["turn_id"],
                    None,
                    "decision_interrupted",
                    {"code": "process_restarted"},
                )
            return len(rows)

    def _payload_bytes(self) -> int:
        total = 0
        for table in ("operations", "checkpoints", "records", "traces"):
            total += cast(
                int,
                self._db.execute(
                    f"SELECT COALESCE(SUM(length(payload)),0) FROM {table}"
                ).fetchone()[0],
            )
        return total


def _delta_dict(delta: StateDelta) -> JSONObject:
    return {
        "state_version": delta.state_version,
        "ack_event_id": delta.ack_event_id,
        "changes": list(delta.changes),
        "events": list(delta.events),
    }


def _delta_from_record(record: JSONObject) -> StateDelta:
    return StateDelta(
        state_version=cast(int, record["version"]),
        ack_event_id=cast(int, record["ack_event_id"]),
        changes=tuple(cast(list[JSONObject], record["changes"])),
        events=tuple(cast(list[JSONObject], record["events"])),
    )
