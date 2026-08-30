from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import CardSelection, Choice, DecisionRequest, DuelEvent, EffectDescriptor


class ProtocolError(ValueError):
    """A client message violates a supported agent_client protocol contract."""


SUPPORTED_PROTOCOL_VERSIONS = frozenset({2, 3})


@dataclass
class _DuelState:
    revision: int = 0
    state: dict[str, Any] | None = None
    last_event_id: int = 0
    observed_life_points: dict[str, int] = field(default_factory=dict)
    duel_ended: dict[str, Any] | None = None
    last_observation_event_id: int = 0


@dataclass
class ProtocolSession:
    """State reducer for one or more client sessions and duels."""

    _duels: dict[tuple[str, str], _DuelState] = field(default_factory=dict)
    events: list[DuelEvent] = field(default_factory=list)

    def ingest_message(self, message: dict[str, Any]) -> DecisionRequest | None:
        if message.get("type") == "duel_event":
            self._ingest_event(message)
            return None
        if message.get("type") != "decision_request":
            return None
        self._validate_protocol_version(message)
        key = (self._string(message, "session_id"), self._string(message, "duel_id"))
        duel = self._duels.setdefault(key, _DuelState())
        event_id = self._integer(message, "event_id")
        if event_id <= duel.last_event_id:
            raise ProtocolError("event_id must strictly increase within a duel")
        duel.last_event_id = event_id
        self._apply_state_delta(duel, message)
        return self._parse_request(message)

    def _ingest_event(self, message: dict[str, Any]) -> None:
        self._validate_protocol_version(message)
        session_id = self._string(message, "session_id")
        duel_id = self._string(message, "duel_id")
        event_id = self._integer(message, "event_id")
        kind = self._string(message, "event")
        duel = self._duels.setdefault((session_id, duel_id), _DuelState())
        if event_id <= duel.last_event_id:
            raise ProtocolError("event_id must strictly increase within a duel")
        duel.last_event_id = event_id
        self._apply_observation(duel, message)
        self.events.append(DuelEvent(session_id, duel_id, event_id, kind, copy.deepcopy(message)))

    def ingest_log_record(self, record: dict[str, Any]) -> DecisionRequest | None:
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        return self.ingest_message(message)

    def state_at_last_decision(self, session_id: str, duel_id: str) -> dict[str, Any]:
        """Return the field state carried by the most recent decision request.

        Fact events received after that request are intentionally not folded into
        this value. Use :meth:`observed_state_for` for the small event projection.
        """

        duel = self._duels.get((session_id, duel_id))
        if duel is None or duel.state is None:
            raise KeyError("no state is available for this session and duel")
        return copy.deepcopy(duel.state)

    def state_for(self, session_id: str, duel_id: str) -> dict[str, Any]:
        """Compatibility alias for :meth:`state_at_last_decision`."""

        return self.state_at_last_decision(session_id, duel_id)

    def observed_state_for(self, session_id: str, duel_id: str) -> dict[str, Any]:
        """Return a partial projection derived from explicit fact events.

        This is not a complete duel-field state. Absent players or fields have not
        been observed by this reducer and must not be treated as default values.
        """

        duel = self._duels.get((session_id, duel_id))
        if duel is None:
            raise KeyError("no observations are available for this session and duel")
        return {
            "life_points": copy.deepcopy(duel.observed_life_points),
            "duel_ended": copy.deepcopy(duel.duel_ended),
            "as_of_event_id": duel.last_observation_event_id,
        }

    @staticmethod
    def _apply_observation(duel: _DuelState, message: dict[str, Any]) -> None:
        kind = message.get("event")
        if kind == "life_points_changed":
            player, after = message.get("player"), message.get("after")
            if isinstance(player, str) and isinstance(after, int) and not isinstance(after, bool):
                duel.observed_life_points[player] = after
                duel.last_observation_event_id = int(message["event_id"])
            return
        if kind != "duel_ended":
            return
        duel.duel_ended = {
            key: copy.deepcopy(message[key])
            for key in ("winner", "reason", "raw_winner")
            if key in message
        }
        duel.duel_ended["event_id"] = message["event_id"]
        duel.last_observation_event_id = int(message["event_id"])

    def _apply_state_delta(self, duel: _DuelState, message: dict[str, Any]) -> None:
        revision = self._integer(message, "state_revision")
        delta = message.get("state_delta")
        if not isinstance(delta, dict):
            raise ProtocolError("state_delta must be an object")
        mode = delta.get("mode")
        if mode == "snapshot":
            data = delta.get("data")
            if not isinstance(data, dict):
                raise ProtocolError("snapshot data must be an object")
            duel.state = copy.deepcopy(data)
            duel.revision = revision
            return
        if mode == "json_patch":
            if duel.state is None:
                raise ProtocolError("json_patch received before snapshot")
            if message.get("base_state_revision") != duel.revision:
                raise ProtocolError("base_state_revision does not match local state")
            if revision <= duel.revision:
                raise ProtocolError("json_patch state_revision must advance")
            operations = delta.get("data")
            if not isinstance(operations, list):
                raise ProtocolError("json_patch data must be an array")
            for operation in operations:
                self._apply_patch(duel.state, operation)
            duel.revision = revision
            return
        if mode == "none":
            if duel.state is None or revision != duel.revision:
                raise ProtocolError("none delta must retain an existing state revision")
            return
        raise ProtocolError("unknown state_delta mode")

    def _parse_request(self, message: dict[str, Any]) -> DecisionRequest:
        decision = message.get("decision")
        if not isinstance(decision, dict):
            raise ProtocolError("decision must be an object")
        raw_choices = decision.get("choices", [])
        raw_cards = decision.get("card_choices", [])
        if not isinstance(raw_choices, list) or not isinstance(raw_cards, list):
            raise ProtocolError("decision choices must be arrays")
        choices = tuple(self._parse_choice(value) for value in raw_choices)
        cards = tuple(self._parse_card_choice(value) for value in raw_cards)
        return DecisionRequest(
            request_id=self._integer(message, "request_id"),
            session_id=self._string(message, "session_id"),
            duel_id=self._string(message, "duel_id"),
            event_id=self._integer(message, "event_id"),
            state_revision=self._integer(message, "state_revision"),
            kind=self._string(decision, "kind"),
            choices=choices,
            card_choices=cards,
            min_cards=self._optional_integer(decision, "min", 0),
            max_cards=self._optional_integer(decision, "max", len(cards)),
            selection_hint=self._optional_object(decision, "selection_hint"),
            raw=copy.deepcopy(message),
        )

    @staticmethod
    def _parse_choice(value: Any) -> Choice:
        if not isinstance(value, dict):
            raise ProtocolError("choice must be an object")
        card = value.get("card")
        if card is not None and not isinstance(card, dict):
            raise ProtocolError("choice card must be an object")
        option = value.get("option")
        if option is not None and not isinstance(option, dict):
            raise ProtocolError("choice option must be an object")
        effect = ProtocolSession._parse_effect(value.get("effect_candidate"))
        choice_id = ProtocolSession._integer(value, "id")
        action = ProtocolSession._string(value, "action")
        return Choice(
            choice_id,
            action,
            copy.deepcopy(card),
            effect,
            copy.deepcopy(option),
            copy.deepcopy(value),
        )

    @staticmethod
    def _parse_effect(value: Any) -> EffectDescriptor | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ProtocolError("effect_candidate must be an object")
        description_id = ProtocolSession._integer(value, "description_id")
        description_offset = value.get("description_offset")
        if description_offset is not None and not isinstance(description_offset, int):
            raise ProtocolError("description_offset must be an integer or null")
        description_text = value.get("description_text")
        if description_text is not None and not isinstance(description_text, str):
            raise ProtocolError("description_text must be a string")
        return EffectDescriptor(
            description_id=description_id,
            description_offset=description_offset,
            description_text=description_text,
            engine_candidate_index=ProtocolSession._nullable_integer(
                value, "engine_candidate_index"
            ),
            raw_flags=ProtocolSession._nullable_integer(value, "raw_flags"),
            operation=ProtocolSession._nullable_boolean(value, "operation"),
            reset=ProtocolSession._nullable_boolean(value, "reset"),
            forced=ProtocolSession._nullable_boolean(value, "forced"),
            raw=copy.deepcopy(value),
        )

    @staticmethod
    def _parse_card_choice(value: Any) -> CardSelection:
        if not isinstance(value, dict) or not isinstance(value.get("card"), dict):
            raise ProtocolError("card choice must include a card object")
        return CardSelection(
            ProtocolSession._integer(value, "index"),
            copy.deepcopy(value["card"]),
            ProtocolSession._integer(value, "selection_sequence"),
        )

    @staticmethod
    def _validate_protocol_version(message: dict[str, Any]) -> None:
        if message.get("protocol_version") not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ProtocolError("unsupported protocol_version")

    @staticmethod
    def _integer(value: dict[str, Any], key: str) -> int:
        result = value.get(key)
        if not isinstance(result, int):
            raise ProtocolError(f"{key} must be an integer")
        return result

    @staticmethod
    def _optional_integer(value: dict[str, Any], key: str, default: int) -> int:
        result = value.get(key, default)
        if not isinstance(result, int):
            raise ProtocolError(f"{key} must be an integer")
        return result

    @staticmethod
    def _nullable_integer(value: dict[str, Any], key: str) -> int | None:
        result = value.get(key)
        if result is not None and not isinstance(result, int):
            raise ProtocolError(f"{key} must be an integer or null")
        return result

    @staticmethod
    def _nullable_boolean(value: dict[str, Any], key: str) -> bool | None:
        result = value.get(key)
        if result is not None and not isinstance(result, bool):
            raise ProtocolError(f"{key} must be a boolean or null")
        return result

    @staticmethod
    def _optional_object(value: dict[str, Any], key: str) -> dict[str, Any] | None:
        result = value.get(key)
        if result is not None and not isinstance(result, dict):
            raise ProtocolError(f"{key} must be an object")
        return copy.deepcopy(result)

    @staticmethod
    def _string(value: dict[str, Any], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str) or not result:
            raise ProtocolError(f"{key} must be a non-empty string")
        return result

    @staticmethod
    def _apply_patch(document: dict[str, Any], operation: Any) -> None:
        if not isinstance(operation, dict):
            raise ProtocolError("patch operation must be an object")
        op, path = operation.get("op"), operation.get("path")
        if op not in {"add", "remove", "replace"} or not isinstance(path, str):
            raise ProtocolError("unsupported RFC 6902 operation")
        tokens = [
            token.replace("~1", "/").replace("~0", "~") for token in path.lstrip("/").split("/")
        ]
        if not tokens or tokens == [""]:
            raise ProtocolError("root patch is not supported")
        parent: Any = document
        for token in tokens[:-1]:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        last = tokens[-1]
        if isinstance(parent, list):
            if op == "add" and last == "-":
                parent.append(copy.deepcopy(operation["value"]))
            elif op == "remove":
                parent.pop(int(last))
            elif op == "replace":
                parent[int(last)] = copy.deepcopy(operation["value"])
            else:
                parent.insert(int(last), copy.deepcopy(operation["value"]))
            return
        if op == "remove":
            del parent[last]
        else:
            parent[last] = copy.deepcopy(operation["value"])


def replay_jsonl(path: Path) -> list[DecisionRequest]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    records.sort(key=lambda record: record.get("event_id", -1))
    session = ProtocolSession()
    requests: list[DecisionRequest] = []
    for record in records:
        request = session.ingest_log_record(record)
        if request is not None:
            requests.append(request)
    return requests
