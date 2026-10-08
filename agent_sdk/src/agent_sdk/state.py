"""Deterministic, perspective-isolated v2 observation state.

The store records observations, not rule conclusions. A diff describes only the
net difference between two visible snapshots; events remain separate evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, cast

type JSONObject = dict[str, Any]

_OBSERVATION_FIELDS = {
    "self_player",
    "turn_player",
    "turn",
    "phase",
    "life_points",
    "zones",
    "events",
    "disabled_field",
    "graveyard_inspection_allowed",
    "chain_depth",
    "test_role",
}
_ZONE_FIELDS = {"player", "name", "count", "hidden_count", "cards"}
_ZONE_NAMES = {"deck", "hand", "monster", "spell", "graveyard", "banished", "extra"}
_CARD_FIELDS = {
    "instance_id",
    "controller",
    "location",
    "sequence",
    "position",
    "known",
    "card_id",
    "owner",
    "attack",
    "defense",
    "level",
    "rank",
    "link",
    "link_marker",
    "type",
    "attribute",
    "race",
    "base_attack",
    "base_defense",
    "left_scale",
    "right_scale",
    "counters",
    "overlay_count",
    "overlay_cards",
    "equipped_to",
    "targets",
    "hint_type",
    "hint_value",
    "description_hints",
}
_CARD_DYNAMIC = _CARD_FIELDS - {
    "instance_id",
    "controller",
    "location",
    "sequence",
    "position",
    "known",
    "card_id",
    "owner",
    "hint_type",
    "hint_value",
    "description_hints",
}
_EVENT_FIELDS = {
    "event_id",
    "kind",
    "source",
    "agent",
    "message_type",
    "option",
    "attacker_attack",
    "attacker_defense",
    "attacker_location",
    "attacker_player",
    "attacker_sequence",
    "card_id",
    "cards",
    "chain_index",
    "controller",
    "count",
    "description_id",
    "from_location",
    "from_player",
    "from_position",
    "from_sequence",
    "hint_type",
    "location",
    "phase",
    "player",
    "reason_flags",
    "reason",
    "results",
    "sequence",
    "target_attack",
    "target_defense",
    "target_location",
    "target_player",
    "target_sequence",
    "targets",
    "to_location",
    "to_player",
    "to_position",
    "to_sequence",
    "turn",
    "value",
    "winner",
    "zone",
}
_EVENT_TEXT_FIELDS = {"kind", "source", "phase", "zone", "from_position", "to_position", "option"}
_CARD_NUMERIC_FIELDS = {
    "attack",
    "defense",
    "level",
    "rank",
    "link",
    "link_marker",
    "type",
    "attribute",
    "race",
    "base_attack",
    "base_defense",
    "left_scale",
    "right_scale",
    "overlay_count",
    "hint_type",
    "hint_value",
}
_CARD_SIGNED_FIELDS = {"attack", "defense", "base_attack", "base_defense"}
_EVENT_SIGNED_FIELDS = {
    "attacker_attack", "attacker_defense", "target_attack", "target_defense"
}
_PHASES = {
    "draw", "standby", "main_1", "battle_start", "battle_step", "damage",
    "damage_calculation", "battle", "main_2", "end", "unknown",
}
_POSITIONS = {
    "face_up_attack", "face_up_defense", "face_down_attack", "face_down_defense",
    "face_up", "face_down", "unknown",
}
_LOCATION_CODES = {
    "deck": 1, "hand": 2, "monster": 4, "spell": 8, "graveyard": 16,
    "banished": 32, "extra": 64,
}


def _only_fields(data: JSONObject, allowed: set[str], name: str) -> None:
    if unknown := data.keys() - allowed:
        raise StateError("invalid_state", f"{name}: unknown fields {sorted(unknown)}")


class StateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class StateDelta:
    state_version: int
    ack_event_id: int
    changes: tuple[JSONObject, ...]
    events: tuple[JSONObject, ...]


@dataclass
class _DuelState:
    database_sha256: str
    events: list[JSONObject] = field(default_factory=lambda: list[JSONObject]())
    snapshots: dict[int, JSONObject] = field(default_factory=lambda: dict[int, JSONObject]())
    snapshot_event_ids: dict[int, int] = field(default_factory=lambda: dict[int, int]())
    decisions: dict[int, str] = field(default_factory=lambda: dict[int, str]())
    deltas: dict[int, StateDelta] = field(default_factory=lambda: dict[int, StateDelta]())

    @property
    def version(self) -> int:
        return max(self.snapshots, default=0)


def _object(value: object, name: str) -> JSONObject:
    if not isinstance(value, dict) or any(
        not isinstance(k, str) for k in cast(dict[object, object], value)
    ):
        raise StateError("invalid_state", f"{name}: expected an object with string keys")
    return cast(JSONObject, value)


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise StateError("invalid_state", f"{name}: expected integer >= {minimum}")
    return value


def _signed_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise StateError("invalid_state", f"{name}: expected integer")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise StateError("invalid_state", f"{name}: expected nonempty string")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise StateError("invalid_state", f"{name}: expected boolean")
    return value


def _clone_json(value: object) -> JSONObject:
    obj = _object(value, "document")
    try:
        encoded = json.dumps(obj, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return cast(JSONObject, json.loads(encoded))
    except (TypeError, ValueError, OverflowError) as exc:
        raise StateError("invalid_state", "document must contain finite JSON values") from exc


def _fingerprint(value: JSONObject) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _identity(envelope: JSONObject) -> tuple[str, str, str]:
    if type(envelope.get("schema_version")) is not int or envelope["schema_version"] not in (2, 3):
        raise StateError("unsupported_version", "schema_version must be 2 or 3")
    session = _string(envelope.get("session_id"), "session_id")
    duel = _string(envelope.get("duel_id"), "duel_id")
    digest = _string(envelope.get("database_sha256"), "database_sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise StateError("invalid_state", "database_sha256: expected lowercase SHA256")
    if not _boolean(envelope.get("history_complete"), "history_complete"):
        raise StateError("history_incomplete", "client reports incomplete event history")
    return session, duel, digest


def _validate_events(value: object) -> list[JSONObject]:
    if not isinstance(value, list):
        raise StateError("invalid_state", "events: expected array")
    events: list[JSONObject] = []
    previous = 0
    for item in cast(list[object], value):
        event = _object(item, "event")
        _only_fields(event, _EVENT_FIELDS, "event")
        event_id = _integer(event.get("event_id"), "event.event_id", 1)
        if event_id <= previous:
            raise StateError("event_order", "event IDs must increase strictly within the batch")
        previous = event_id
        _string(event.get("kind"), "event.kind")
        if event["kind"] == "control_changed":
            if event.get("source") != "client_control" or "agent" not in event:
                raise StateError("invalid_state", "control_changed requires source and agent")
        elif "source" in event or "agent" in event:
            raise StateError("invalid_state", "control fields require control_changed")
        if "option" in event and (
            event["kind"] != "hint_observed"
            or event.get("hint_type") != 4
            or (event.get("value"), event["option"]) not in ((60, "heads"), (61, "tails"))
        ):
            raise StateError("invalid_state", "event.option: invalid selected coin face")
        random_kind = event["kind"] in {"coin_tossed", "dice_rolled"}
        if random_kind:
            coin = event["kind"] == "coin_tossed"
            if event.get("message_type") != (130 if coin else 131):
                raise StateError("invalid_state", "random result message type mismatch")
            if _integer(event.get("player"), "event.player") > 1:
                raise StateError("invalid_state", "event.player: expected 0 or 1")
            count = _integer(event.get("count"), "event.count", 1)
            if count > (20 if coin else 5):
                raise StateError("invalid_state", "event.count: too many random results")
            results = event.get("results")
            if not isinstance(results, list) or len(cast(list[object], results)) != count:
                raise StateError("invalid_state", "event.results: count mismatch")
            for result in cast(list[object], results):
                if coin:
                    if result not in ("heads", "tails"):
                        raise StateError("invalid_state", "event.results: invalid coin face")
                elif _integer(result, "event.results", 1) > 6:
                    raise StateError("invalid_state", "event.results: invalid die face")
        elif "results" in event:
            raise StateError("invalid_state", "event.results requires a random result event")
        for name, field_value in event.items():
            if name in {"event_id", "cards", "targets", "results"}:
                continue
            if name == "agent":
                _boolean(field_value, "event.agent")
                continue
            if name in _EVENT_TEXT_FIELDS:
                _string(field_value, f"event.{name}")
            elif name in _EVENT_SIGNED_FIELDS:
                _signed_integer(field_value, f"event.{name}")
            else:
                _integer(field_value, f"event.{name}")
        if "phase" in event and event["phase"] not in _PHASES:
            raise StateError("invalid_state", "event.phase: unknown phase")
        for name in ("from_position", "to_position"):
            if name in event and event[name] not in _POSITIONS:
                raise StateError("invalid_state", f"event.{name}: unknown position")
        for list_name in ("cards", "targets"):
            if list_name not in event:
                continue
            entries = event[list_name]
            if not isinstance(entries, list):
                raise StateError("invalid_state", f"event.{list_name}: expected array")
            for entry in cast(list[object], entries):
                visible = _object(entry, f"event.{list_name} item")
                _only_fields(
                    visible,
                    {"player", "location", "sequence", "card_id"},
                    f"event.{list_name} item",
                )
                for name, field_value in visible.items():
                    _integer(field_value, f"event.{list_name}.{name}")
                if "card_id" in visible:
                    _integer(visible["card_id"], "event card_id", 1)
        events.append(event)
    return events


def _merge_events(existing: list[JSONObject], incoming: list[JSONObject]) -> list[JSONObject]:
    merged = existing.copy()
    for event in incoming:
        event_id = cast(int, event["event_id"])
        if event_id <= len(merged):
            if _fingerprint(merged[event_id - 1]) != _fingerprint(event):
                raise StateError(
                    "event_conflict", f"event {event_id} was replayed with different content"
                )
        elif event_id == len(merged) + 1:
            merged.append(event)
        else:
            raise StateError("event_gap", f"expected event {len(merged) + 1}, got {event_id}")
    return merged


def _validate_snapshot(value: object) -> JSONObject:
    observation = _object(value, "observation")
    _only_fields(observation, _OBSERVATION_FIELDS, "observation")
    for key in ("self_player", "turn_player"):
        if _integer(observation.get(key), key) > 1:
            raise StateError("invalid_state", f"{key}: expected 0 or 1")
    if observation["self_player"] != 0:
        raise StateError("invalid_state", "self_player must be 0 in the local perspective")
    _integer(observation.get("turn"), "turn")
    if _string(observation.get("phase"), "phase") not in _PHASES:
        raise StateError("invalid_state", "phase: unknown phase")
    for key in ("disabled_field", "chain_depth"):
        if key in observation:
            _integer(observation[key], key)
    if "test_role" in observation:
        role = _string(observation["test_role"], "test_role")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", role):
            raise StateError("invalid_state", "test_role: invalid identifier")
    inspect_grave = observation.get("graveyard_inspection_allowed", True)
    _boolean(inspect_grave, "graveyard_inspection_allowed")
    points = observation.get("life_points")
    if not isinstance(points, list) or len(cast(list[object], points)) != 2:
        raise StateError("invalid_state", "life_points: expected two values")
    for point in cast(list[object], points):
        _integer(point, "life_points item")
    zones = observation.get("zones")
    if not isinstance(zones, list):
        raise StateError("invalid_state", "zones: expected array")
    seen_zones: set[tuple[int, str]] = set()
    for item in cast(list[object], zones):
        zone = _object(item, "zone")
        _only_fields(zone, _ZONE_FIELDS, "zone")
        player = _integer(zone.get("player"), "zone.player")
        if player > 1:
            raise StateError("invalid_state", "zone.player: expected 0 or 1")
        name = _string(zone.get("name"), "zone.name")
        if name not in _ZONE_NAMES:
            raise StateError("invalid_state", f"unknown zone name: {name}")
        key = (player, name)
        if key in seen_zones:
            raise StateError("invalid_state", f"duplicate zone {key}")
        seen_zones.add(key)
        count = _integer(zone.get("count"), "zone.count")
        cards = zone.get("cards")
        if not isinstance(cards, list) or len(cast(list[object], cards)) > count:
            raise StateError("invalid_state", "zone.cards: expected at most zone.count cards")
        if (
            name == "deck"
            or (name == "hand" and player == 1)
            or (name == "graveyard" and not inspect_grave)
        ) and cards:
            raise StateError("hidden_identity", f"{name} identities are not inspectable")
        if "hidden_count" in zone:
            hidden_count = _integer(zone["hidden_count"], "zone.hidden_count")
            if hidden_count != count - len(cast(list[object], cards)):
                raise StateError("invalid_state", "zone.hidden_count must equal count - len(cards)")
        seen_slots: set[int] = set()
        for item_card in cast(list[object], cards):
            card = _object(item_card, "card")
            _only_fields(card, _CARD_FIELDS, "card")
            sequence = _integer(card.get("sequence"), "card.sequence")
            if sequence in seen_slots:
                raise StateError("invalid_state", "duplicate card position")
            seen_slots.add(sequence)
            if card.get("controller") != player or card.get("location") != name:
                raise StateError("invalid_state", "card position does not match zone")
            known = card.get("known", card.get("public", False))
            _boolean(known, "card.known")
            position = _string(card.get("position", "unknown"), "card.position")
            if position not in _POSITIONS:
                raise StateError("invalid_state", "card.position: unknown position")
            if "instance_id" in card:
                instance_id = _string(card["instance_id"], "card.instance_id")
                expected = f"{player}:{_LOCATION_CODES[name]}:{sequence}"
                if instance_id != expected:
                    raise StateError("invalid_state", "card.instance_id is not its position key")
            for field_name in _CARD_NUMERIC_FIELDS & card.keys():
                field_value = card[field_name]
                if field_value is not None:
                    if field_name in _CARD_SIGNED_FIELDS:
                        _signed_integer(field_value, f"card.{field_name}")
                    else:
                        _integer(field_value, f"card.{field_name}")
            if "counters" in card:
                counters = _object(card["counters"], "card.counters")
                for counter_type, amount in counters.items():
                    if not counter_type.isdecimal():
                        raise StateError("invalid_state", "counter type must be numeric")
                    _integer(amount, "card.counter amount")
            if "description_hints" in card:
                descriptions = card["description_hints"]
                if not isinstance(descriptions, list):
                    raise StateError("invalid_state", "description_hints must be an array")
                seen_descriptions: set[int] = set()
                for item_hint in cast(list[object], descriptions):
                    hint = _object(item_hint, "card.description_hints item")
                    _only_fields(hint, {"description_id", "count"}, "card.description_hints item")
                    description_id = _signed_integer(
                        hint.get("description_id"), "card.description_hints.description_id"
                    )
                    _integer(hint.get("count"), "card.description_hints.count", 1)
                    if description_id in seen_descriptions:
                        raise StateError("invalid_state", "duplicate description hint")
                    seen_descriptions.add(description_id)
            if player == 1 and name in ("extra", "banished"):
                if not known or not position.startswith("face_up") or "card_id" not in card:
                    raise StateError("hidden_identity", f"opponent {name} card is not public")
            if not known and "card_id" in card:
                raise StateError("hidden_identity", "hidden card includes card_id")
            if not known:
                opaque_fields = {
                    "instance_id",
                    "controller",
                    "location",
                    "sequence",
                    "position",
                    "known",
                    "public",
                }
                leaked = card.keys() - opaque_fields
                if leaked:
                    raise StateError(
                        "hidden_identity",
                        f"hidden card includes visible attributes: {sorted(leaked)}",
                    )
            if "card_id" in card:
                _integer(card["card_id"], "card.card_id", 1)
            if (card.keys() & _CARD_DYNAMIC and not position.startswith("face_up")
                    and not (name == "graveyard" and position == "unknown")):
                raise StateError("hidden_identity", "face-down card includes public dynamic data")
            if "owner" in card and _integer(card["owner"], "card.owner") > 1:
                raise StateError("invalid_state", "card.owner must be 0 or 1")
            if "overlay_cards" in card:
                materials = card["overlay_cards"]
                if not isinstance(materials, list):
                    raise StateError("invalid_state", "overlay_cards must be an array")
                if (type(card.get("overlay_count")) is int
                        and len(cast(list[object], materials)) > card["overlay_count"]):
                    raise StateError("invalid_state", "overlay_cards exceed overlay_count")
                for material in cast(list[object], materials):
                    overlay = _object(material, "overlay card")
                    _only_fields(overlay, {"instance_id", "card_id"}, "overlay card")
                    material_id = _string(overlay.get("instance_id"), "overlay.instance_id")
                    host_id = card.get("instance_id")
                    if host_id is not None and not re.fullmatch(
                        re.escape(host_id) + r":overlay:\d+", material_id
                    ):
                        raise StateError("invalid_state", "overlay key does not match host")
                    if "card_id" in overlay:
                        _integer(overlay["card_id"], "overlay.card_id", 1)
            if "targets" in card:
                targets = card["targets"]
                if not isinstance(targets, list):
                    raise StateError("invalid_state", "card.targets must be an array")
                for target in cast(list[object], targets):
                    if not re.fullmatch(r"[01]:\d+:\d+", _string(target, "card.target")):
                        raise StateError("invalid_state", "card.target: invalid position key")
            if "equipped_to" in card:
                equipped_to = _string(card["equipped_to"], "card.equipped_to")
                if not re.fullmatch(r"[01]:\d+:\d+", equipped_to):
                    raise StateError("invalid_state", "card.equipped_to: invalid position key")
    return observation


def _zones(snapshot: JSONObject) -> dict[tuple[int, str], JSONObject]:
    return {(z["player"], z["name"]): z for z in cast(list[JSONObject], snapshot["zones"])}


def _ambiguous_zone(old_zone: JSONObject | None, new_zone: JSONObject | None) -> bool:
    for zone in (old_zone, new_zone):
        if zone is None:
            continue
        cards = cast(list[JSONObject], zone["cards"])
        card_ids = [card["card_id"] for card in cards if "card_id" in card]
        if len(card_ids) != len(set(card_ids)):
            return True
        if any(card.get("known") is False for card in cards):
            return True
    return False


def _snapshot_diff(before: JSONObject | None, after: JSONObject) -> tuple[JSONObject, ...]:
    if before is None:
        return ({"kind": "initial_snapshot"},)
    changes: list[JSONObject] = []
    excluded = {"zones", "events"}
    for key in sorted((before.keys() | after.keys()) - excluded):
        old, new = before.get(key), after.get(key)
        if old != new:
            changes.append({"kind": "scalar", "field": key, "before": old, "after": new})
    old_zones, new_zones = _zones(before), _zones(after)
    for zone_key in sorted(old_zones.keys() | new_zones.keys()):
        old_zone, new_zone = old_zones.get(zone_key), new_zones.get(zone_key)
        player, name = zone_key
        old_count = old_zone["count"] if old_zone else None
        new_count = new_zone["count"] if new_zone else None
        if old_count != new_count:
            changes.append(
                {
                    "kind": "zone_count",
                    "player": player,
                    "zone": name,
                    "before": old_count,
                    "after": new_count,
                }
            )
        old_hidden = old_zone.get("hidden_count") if old_zone else None
        new_hidden = new_zone.get("hidden_count") if new_zone else None
        old_list = old_zone["cards"] if old_zone else None
        new_list = new_zone["cards"] if new_zone else None
        if name == "hand" or old_hidden != new_hidden or _ambiguous_zone(old_zone, new_zone):
            if old_list != new_list or old_hidden != new_hidden:
                changes.append(
                    {
                        "kind": "zone_contents_changed",
                        "player": player,
                        "zone": name,
                        "before_hidden_count": old_hidden,
                        "after_hidden_count": new_hidden,
                    }
                )
            continue
        old_cards = {c["sequence"]: c for c in old_zone["cards"]} if old_zone else {}
        new_cards = {c["sequence"]: c for c in new_zone["cards"]} if new_zone else {}
        for sequence in sorted(old_cards.keys() | new_cards.keys()):
            old_card, new_card = old_cards.get(sequence), new_cards.get(sequence)
            if old_card is None or new_card is None:
                changes.append(
                    {
                        "kind": "slot",
                        "player": player,
                        "zone": name,
                        "sequence": sequence,
                        "before": old_card,
                        "after": new_card,
                    }
                )
                continue
            for field_name in sorted(old_card.keys() | new_card.keys()):
                old_value, new_value = old_card.get(field_name), new_card.get(field_name)
                if old_value != new_value:
                    changes.append(
                        {
                            "kind": "card_attribute",
                            "player": player,
                            "zone": name,
                            "sequence": sequence,
                            "field": field_name,
                            "before": old_value,
                            "after": new_value,
                        }
                    )
    return tuple(changes)


class StateStore:
    """In-memory state processor. Persistence and model scheduling belong to the service."""

    def __init__(self) -> None:
        self._duels: dict[tuple[str, str], _DuelState] = {}
        self._lock = threading.RLock()

    def export_duel(self, session_id: str, duel_id: str) -> JSONObject:
        """Export one perspective for a durable checkpoint."""
        with self._lock:
            current = self._duels.get((session_id, duel_id))
            if current is None:
                raise StateError("state_not_found", "duel is unavailable")
            records: list[JSONObject] = []
            for version in range(1, current.version + 1):
                delta = current.deltas[version]
                records.append(
                    {
                        "version": version,
                        "snapshot": copy.deepcopy(current.snapshots[version]),
                        "ack_event_id": current.snapshot_event_ids[version],
                        "decision_fingerprint": current.decisions[version],
                        "changes": copy.deepcopy(list(delta.changes)),
                        "events": copy.deepcopy(list(delta.events)),
                    }
                )
            return {
                "format_version": 1,
                "session_id": session_id,
                "duel_id": duel_id,
                "database_sha256": current.database_sha256,
                "events": copy.deepcopy(current.events),
                "records": records,
            }

    def import_duel(self, document: object) -> None:
        """Validate a checkpoint fully, then atomically install its one perspective."""
        data = _clone_json(document)
        if data.get("format_version") != 1:
            raise StateError("invalid_checkpoint", "unsupported checkpoint format")
        session = _string(data.get("session_id"), "session_id")
        duel = _string(data.get("duel_id"), "duel_id")
        digest = _string(data.get("database_sha256"), "database_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise StateError("invalid_checkpoint", "invalid database digest")
        events = _validate_events(data.get("events"))
        _merge_events([], events)
        raw_records = data.get("records")
        if not isinstance(raw_records, list):
            raise StateError("invalid_checkpoint", "records must be an array")
        restored = _DuelState(digest, events=copy.deepcopy(events))
        previous_snapshot: JSONObject | None = None
        previous_ack = 0
        for expected_version, item in enumerate(cast(list[object], raw_records), start=1):
            record = _object(item, "record")
            if _integer(record.get("version"), "record.version", 1) != expected_version:
                raise StateError("invalid_checkpoint", "state versions are not contiguous")
            snapshot = _validate_snapshot(record.get("snapshot"))
            if "events" in snapshot:
                raise StateError("invalid_checkpoint", "checkpoint snapshot contains events")
            ack = _integer(record.get("ack_event_id"), "record.ack_event_id")
            if not previous_ack <= ack <= len(events):
                raise StateError("invalid_checkpoint", "event acknowledgments are not monotonic")
            fingerprint = _string(record.get("decision_fingerprint"), "decision_fingerprint")
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise StateError("invalid_checkpoint", "invalid decision fingerprint")
            changes = record.get("changes")
            observed = record.get("events")
            if not isinstance(changes, list) or not isinstance(observed, list):
                raise StateError("invalid_checkpoint", "invalid delta arrays")
            expected_changes = _snapshot_diff(previous_snapshot, snapshot)
            expected_events = events[previous_ack:ack]
            if changes != list(expected_changes) or observed != expected_events:
                raise StateError("invalid_checkpoint", "checkpoint delta does not match state")
            restored.snapshots[expected_version] = snapshot
            restored.snapshot_event_ids[expected_version] = ack
            restored.decisions[expected_version] = fingerprint
            restored.deltas[expected_version] = StateDelta(
                expected_version,
                ack,
                tuple(copy.deepcopy(expected_changes)),
                tuple(copy.deepcopy(expected_events)),
            )
            previous_snapshot = snapshot
            previous_ack = ack
        with self._lock:
            if (session, duel) in self._duels:
                raise StateError("state_conflict", "duel is already loaded")
            self._duels[(session, duel)] = restored

    def apply_sync(self, envelope: object) -> int:
        """Accept an ordered event batch atomically and return the last acknowledged ID."""
        data = _clone_json(envelope)
        session, duel, digest = _identity(data)
        incoming = _validate_events(data.get("events"))
        if not incoming:
            raise StateError("invalid_state", "sync events must be nonempty")
        key = (session, duel)
        with self._lock:
            current = self._duels.get(key)
            if current is not None and current.database_sha256 != digest:
                raise StateError("database_mismatch", "database digest changed within duel")
            merged = _merge_events(current.events if current else [], incoming)
            if current is None:
                current = _DuelState(digest)
                self._duels[key] = current
            current.events = merged
            return len(merged)

    def apply_decision(self, request: object) -> StateDelta:
        """Validate and commit one versioned observation, including its event tail."""
        data = _clone_json(request)
        session, duel, digest = _identity(data)
        version = _integer(data.get("state_version"), "state_version", 1)
        _integer(data.get("prompt_id"), "prompt_id", 1)
        _object(data.get("prompt"), "prompt")
        observation = _validate_snapshot(data.get("observation"))
        incoming = _validate_events(observation.get("events"))
        snapshot = copy.deepcopy(observation)
        snapshot.pop("events", None)
        fingerprint = _fingerprint(data)
        key = (session, duel)
        with self._lock:
            current = self._duels.get(key)
            if current is not None and current.database_sha256 != digest:
                raise StateError("database_mismatch", "database digest changed within duel")
            last_version = current.version if current else 0
            if version <= last_version:
                assert current is not None
                if current.decisions.get(version) == fingerprint:
                    return copy.deepcopy(current.deltas[version])
                raise StateError(
                    "state_conflict", "state version was replayed with different content"
                )
            if version != last_version + 1:
                raise StateError(
                    "state_gap", f"expected state version {last_version + 1}, got {version}"
                )
            old_events = current.events if current else []
            merged = _merge_events(old_events, incoming)
            prior = current.snapshots.get(last_version) if current else None
            prior_event_id = current.snapshot_event_ids.get(last_version, 0) if current else 0
            delta = StateDelta(
                version,
                len(merged),
                _snapshot_diff(prior, snapshot),
                tuple(copy.deepcopy(event) for event in merged[prior_event_id:]),
            )
            if current is None:
                current = _DuelState(digest)
                self._duels[key] = current
            current.events = merged
            current.snapshots[version] = snapshot
            current.snapshot_event_ids[version] = len(merged)
            current.decisions[version] = fingerprint
            current.deltas[version] = copy.deepcopy(delta)
            return delta

    def get_state(self, session_id: str, duel_id: str, state_version: int) -> JSONObject:
        """Return a detached snapshot at an exact version; never return a newer state."""
        with self._lock:
            current = self._duels.get((session_id, duel_id))
            if current is None or state_version not in current.snapshots:
                raise StateError("state_not_found", "requested state version is unavailable")
            return copy.deepcopy(current.snapshots[state_version])

    def get_status(self, session_id: str, duel_id: str) -> dict[str, int]:
        """Return the accepted checkpoint and event prefix, including for an empty duel."""
        with self._lock:
            current = self._duels.get((session_id, duel_id))
            return {
                "state_version": current.version if current else 0,
                "ack_event_id": len(current.events) if current else 0,
            }

    def get_zone(
        self, session_id: str, duel_id: str, state_version: int, player: int, name: str
    ) -> JSONObject:
        snapshot = self.get_state(session_id, duel_id, state_version)
        for zone in cast(list[JSONObject], snapshot["zones"]):
            if zone["player"] == player and zone["name"] == name:
                return zone
        raise StateError("zone_not_found", "requested zone is unavailable")

    def get_events(
        self,
        session_id: str,
        duel_id: str,
        *,
        state_version: int | None = None,
        after_event_id: int = 0,
        limit: int = 100,
    ) -> tuple[JSONObject, ...]:
        _integer(after_event_id, "after_event_id")
        if _integer(limit, "limit", 1) > 1000:
            raise StateError("invalid_state", "limit must be <= 1000")
        with self._lock:
            current = self._duels.get((session_id, duel_id))
            if current is None:
                raise StateError("state_not_found", "duel is unavailable")
            upper = len(current.events)
            if state_version is not None:
                if state_version not in current.snapshot_event_ids:
                    raise StateError("state_not_found", "requested state version is unavailable")
                upper = current.snapshot_event_ids[state_version]
            return tuple(
                copy.deepcopy(current.events[after_event_id : min(upper, after_event_id + limit)])
            )
