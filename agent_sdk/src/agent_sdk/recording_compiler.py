"""Compile paired manual-client traces into a reviewable scenario draft.

The raw capture is authoritative for deck order and decisions. The compiler never
invent responses or treat a draft as verified; the launcher owns replay validation.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, TypeGuard, cast

import yaml  # pyright: ignore[reportMissingModuleSource]

from .scenario import Scenario, ScenarioError

ROLES = ("host", "guest")
RANDOM_MESSAGES = {
    33: "hand_shuffle",
    36: "set_shuffle",
    81: "random_select",
    130: "coin",
    131: "dice",
}
PUBLIC_ANCHORS = {5: "win", 40: "new_turn", 41: "new_phase"}
PUBLIC_ZONES = {"monster", "spell", "graveyard", "banished"}
ZONE_LABELS = {
    "monster": "怪兽区",
    "spell": "魔法陷阱区",
    "graveyard": "墓地",
    "banished": "除外区",
}
SELECTOR_KEYS = (
    "kind",
    "card_id",
    "description_id",
    "effect_flag",
    "number",
    "bit",
    "weight",
    "controller",
    "location",
)
CARD_SELECTOR_FIELDS = {"card_id", "controller", "location", "sequence"}


def _is_object(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


class _ScenarioDumper(yaml.SafeDumper):
    pass


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    quoted = value.isascii() and value.isdecimal()
    return dumper.represent_scalar(  # pyright: ignore[reportUnknownMemberType]
        "tag:yaml.org,2002:str", value, style='"' if quoted else None
    )


_ScenarioDumper.add_representer(str, _represent_string)


def _card_id_text(value: Any) -> str:
    if type(value) is not int or not 1 <= value <= 0xFFFFFFFF:
        raise RecordingError(f"invalid candidate card_id {value!r}")
    return f"{value:08d}"


class RecordingError(ValueError):
    """A capture cannot yet be compiled into a deterministic scenario."""


def _overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RecordingError(f"{path}: duplicate override key {key!r}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if not _is_object(value):
        raise RecordingError(f"{path}: overrides must be an object")
    result: dict[str, dict[str, Any]] = {}
    for key, entry in value.items():
        if not _is_object(entry):
            raise RecordingError(f"{path}: invalid override entry {key!r}")
        if set(entry) != {"ordinal", "expected_matches"} or any(
            type(entry[field]) is not int or entry[field] < 1
            for field in ("ordinal", "expected_matches")
        ):
            raise RecordingError(f"{path}: invalid override {key!r}")
        result[key] = entry
    return result


def _records(path: Path, role: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RecordingError(f"{role}: missing {path.name}")
    records: list[dict[str, Any]] = []
    previous = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise RecordingError(
                    f"{role}:{line_number}: invalid or truncated JSONL: {exc}"
                ) from exc
            if not _is_object(value):
                raise RecordingError(f"{role}:{line_number}: expected object")
            seq = value.get("seq")
            if type(seq) is not int or seq <= previous or value.get("role") != role:
                raise RecordingError(f"{role}:{line_number}: invalid role or nonmonotonic seq")
            previous = seq
            records.append(value)
    if not records:
        raise RecordingError(f"{role}: empty recording")
    return records


def _single(records: list[dict[str, Any]], kind: str, role: str) -> dict[str, Any]:
    values = [r for r in records if r.get("kind") == kind]
    if len(values) != 1:
        raise RecordingError(f"{role}: expected one {kind}, found {len(values)}")
    return values[0]


def _deck(record: dict[str, Any], role: str) -> str:
    sections: list[str] = []
    for field, marker in (("main", "#main"), ("extra", "#extra"), ("side", "!side")):
        cards = record.get(field)
        if not _is_array(cards) or any(
            type(card) is not int or not 1 <= card <= 0xFFFFFFFF for card in cards
        ):
            raise RecordingError(f"{role} seq {record['seq']}: invalid {field} deck")
        if field == "main" and len(cards) < 5:
            raise RecordingError(f"{role} seq {record['seq']}: main deck has fewer than five cards")
        sections.append(marker + "\n" + "".join(f"{card}\n" for card in cards))
    return "".join(sections)


def _selector(
    candidate: dict[str, Any],
    candidates: list[dict[str, Any]],
    role: str,
    response_seq: int,
    overrides: dict[str, dict[str, Any]],
    used_overrides: set[str],
    ordinal_usages: list[dict[str, Any]],
) -> dict[str, Any]:
    card = candidate.get("card")
    card = card if _is_object(card) else {}
    chosen: dict[str, Any] = {}
    for key in SELECTOR_KEYS:
        source = card if key in CARD_SELECTOR_FIELDS else candidate
        if key not in source:
            continue
        value = source[key]
        if key in {"description_id", "effect_flag", "card_id"} and value == 0:
            continue
        if key == "card_id":
            value = _card_id_text(value)
        chosen[key] = value
    if card.get("location") in PUBLIC_ZONES and type(card.get("sequence")) is int:
        chosen["sequence"] = card["sequence"]
    matches = [item for item in candidates if _matches(item, chosen)]
    if len(matches) == 1:
        return chosen
    cid = candidate.get("id")
    key = f"{role}:{response_seq}:{cid}"
    ordinal = next((i for i, item in enumerate(matches, 1) if item is candidate), None)
    if ordinal is None:
        raise RecordingError(f"{key}: selected candidate absent from prompt")
    expected_matches = len(matches)
    ordinal_usages.append(
        {
            "key": key,
            "role": role,
            "response_seq": response_seq,
            "candidate_id": cid,
            "ordinal": ordinal,
            "expected_matches": expected_matches,
            "selector": chosen,
            "candidates": matches,
        }
    )
    if reviewed := overrides.get(key):
        if reviewed != {"ordinal": ordinal, "expected_matches": expected_matches}:
            raise RecordingError(
                f"{key}: override {reviewed} disagrees with recorded candidate order "
                f"ordinal={ordinal}, expected_matches={expected_matches}"
            )
        used_overrides.add(key)
    return {**chosen, "ordinal": ordinal, "expected_matches": expected_matches}


def _matches(candidate: dict[str, Any], selector: dict[str, Any]) -> bool:
    card = candidate.get("card")
    card = card if _is_object(card) else {}
    for key, value in selector.items():
        source = card if key in CARD_SELECTOR_FIELDS else candidate
        raw = source.get(key)
        actual = (
            _card_id_text(raw)
            if key == "card_id" and type(raw) is int and 1 <= raw <= 0xFFFFFFFF
            else raw
        )
        if actual != value:
            return False
    return True


def _action(
    prompt: dict[str, Any],
    response: dict[str, Any],
    role: str,
    overrides: dict[str, dict[str, Any]],
    used_overrides: set[str],
    ordinal_usages: list[dict[str, Any]],
) -> dict[str, Any]:
    action = response.get("action")
    if not _is_object(action):
        reason = response.get("error", "missing action")
        raise RecordingError(
            f"seq {response['seq']}: undecodable response: {reason}; "
            f"prompt={prompt}; response={response}"
        )
    candidates = prompt.get("candidates")
    if not _is_array(candidates) or any(not _is_object(c) for c in candidates):
        raise RecordingError(f"seq {response['seq']}: malformed prompt candidates")
    by_id = {c.get("id"): c for c in candidates}

    def select(cid: Any) -> dict[str, Any]:
        if cid not in by_id:
            raise RecordingError(f"seq {response['seq']}: unknown candidate {cid!r}")
        try:
            return _selector(
                by_id[cid],
                candidates,
                role,
                response["seq"],
                overrides,
                used_overrides,
                ordinal_usages,
            )
        except RecordingError as exc:
            raise RecordingError(
                f"seq {response['seq']}: {exc}; prompt={prompt}; response={response}"
            ) from exc

    kind = action.get("kind")
    if kind in ("choice", "select_step"):
        return {"kind": kind, "match": select(action.get("candidate_id"))}
    if kind == "select_cards":
        ids = action.get("candidate_ids")
        if not _is_array(ids):
            raise RecordingError(f"seq {response['seq']}: missing candidate_ids")
        return {"kind": kind, "matches": [select(cid) for cid in ids]}
    if kind == "select_places":
        return {"kind": kind, "places": action.get("places")}
    if kind == "distribute_counters":
        allocations = action.get("allocations")
        if not _is_array(allocations):
            raise RecordingError(f"seq {response['seq']}: invalid allocations")
        return {
            "kind": kind,
            "allocations": [
                {"match": select(a.get("candidate_id")), "count": a.get("count")}
                for a in allocations
                if _is_object(a)
            ],
        }
    if kind == "announce_card":
        return {"kind": kind, "card_id": _card_id_text(action.get("card_id"))}
    raise RecordingError(f"seq {response['seq']}: unsupported action kind {kind!r}")


def _normalize_places(
    role: str,
    prompt: dict[str, Any],
    response: dict[str, Any],
    first_player_role: str,
    controller_space: Any,
) -> list[dict[str, Any]]:
    raw_places = cast(dict[str, Any], response["action"]).get("places")
    candidates = prompt.get("candidates")
    if not _is_array(raw_places) or not _is_array(candidates):
        raise RecordingError(f"{role} seq {response['seq']}: missing select_place data")
    legal = {
        (item.get("controller"), item.get("location"), item.get("sequence"))
        for item in candidates
        if _is_object(item) and item.get("kind") == "place"
    }
    if controller_space not in (None, "local", "raw"):
        raise RecordingError(f"{role} seq {response['seq']}: invalid controller_space")
    result: list[dict[str, Any]] = []
    for place in raw_places:
        if not _is_object(place) or set(place) != {"controller", "location", "sequence"}:
            raise RecordingError(f"{role} seq {response['seq']}: malformed selected place")
        controller = place["controller"]
        if type(controller) is not int or controller not in (0, 1):
            raise RecordingError(f"{role} seq {response['seq']}: invalid selected controller")
        same = (controller, place["location"], place["sequence"]) in legal
        mapped = controller ^ int(role != first_player_role)
        converted = (mapped, place["location"], place["sequence"]) in legal
        if controller_space == "local":
            chosen = controller if same else None
        elif controller_space == "raw":
            chosen = mapped if converted else None
        elif same and not converted:
            chosen = controller
        elif converted and not same:
            chosen = mapped
        elif same and converted:
            # Legacy captures omit controller_space. Their decoder emitted raw seats.
            chosen = mapped
        else:
            chosen = None
        if chosen is None:
            raise RecordingError(
                f"{role} seq {response['seq']}: selected place cannot match prompt "
                f"controller_space={controller_space!r}; place={place}; candidates={candidates}"
            )
        result.append({**place, "controller": chosen})
    return result


def _zone_lookup(observation: dict[str, Any], player: Any, name: Any) -> dict[str, Any] | None:
    zones = observation.get("zones")
    if not _is_array(zones):
        return None
    return next(
        (z for z in zones if _is_object(z) and z.get("player") == player and z.get("name") == name),
        None,
    )


def _zone_assertion(zone: dict[str, Any], *, card_id: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"player": zone["player"], "name": zone["name"]}
    if type(zone.get("count")) is int:
        result["count"] = zone["count"]
    cards = zone.get("cards")
    if not _is_array(cards):
        return result
    selected = [c for c in cards if _is_object(c) and type(c.get("card_id")) is int]
    if card_id is not None:
        selected = [c for c in selected if c["card_id"] == card_id]
    if not selected:
        return result
    counts = Counter(c["card_id"] for c in selected)
    contains: list[dict[str, Any]] = []
    for cid, quantity in sorted(counts.items()):
        item: dict[str, Any] = {"card_id": _card_id_text(cid)}
        if quantity > 1:
            item["count"] = quantity
        # Position and field slot are stable for a unique public field card.
        if quantity == 1 and zone["name"] in ("monster", "spell"):
            card = next(c for c in selected if c["card_id"] == cid)
            if isinstance(card.get("position"), str):
                item["position"] = card["position"]
            if type(card.get("sequence")) is int:
                item["sequence"] = card["sequence"]
        contains.append(item)
    result["contains"] = contains
    return result


def _zone_signature(zone: dict[str, Any]) -> tuple[Any, ...]:
    cards = zone.get("cards")
    visible = (
        tuple(
            sorted(
                (
                    (c.get("card_id"), c.get("position"), c.get("sequence"))
                    for c in cards
                    if _is_object(c)
                ),
                key=repr,
            )
        )
        if _is_array(cards)
        else ()
    )
    return (zone.get("count"), visible)


def _expect(
    prompt: dict[str, Any],
    observation: dict[str, Any],
    action: dict[str, Any],
    previous_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"prompt": prompt["kind"]}
    for field in ("turn", "phase", "turn_player"):
        if field in observation:
            result[field] = observation[field]
    wanted: dict[tuple[int, str], dict[str, Any]] = {}
    selectors: list[dict[str, Any]] = []
    if isinstance(action.get("match"), dict):
        selectors.append(action["match"])
    if isinstance(action.get("matches"), list):
        selectors.extend(s for s in action["matches"] if _is_object(s))
    if isinstance(action.get("allocations"), list):
        selectors.extend(
            a["match"]
            for a in action["allocations"]
            if _is_object(a) and isinstance(a.get("match"), dict)
        )
    for selector in selectors:
        player, name = selector.get("controller"), selector.get("location")
        if type(player) is not int or not isinstance(name, str):
            continue
        zone = _zone_lookup(observation, player, name)
        if zone is None:
            continue
        cid = selector.get("card_id")
        cid_int = int(cid) if isinstance(cid, str) and cid.isdecimal() else None
        wanted[(player, name)] = _zone_assertion(zone, card_id=cid_int)
    if action.get("kind") == "select_places":
        for place in action.get("places", []):
            if not _is_object(place):
                continue
            player, name = place.get("controller"), place.get("location")
            if type(player) is not int or not isinstance(name, str):
                continue
            zone = _zone_lookup(observation, player, name)
            if zone is not None:
                wanted[(player, name)] = _zone_assertion(zone)
    if previous_observation is not None:
        zones = observation.get("zones")
        if _is_array(zones):
            for zone in zones:
                if not _is_object(zone):
                    continue
                player, name = zone.get("player"), zone.get("name")
                if type(player) is not int or not isinstance(name, str):
                    continue
                previous = _zone_lookup(previous_observation, player, name)
                if previous is not None and _zone_signature(previous) != _zone_signature(zone):
                    wanted[(player, name)] = _zone_assertion(zone)
    if wanted:
        result["zones"] = list(wanted.values())
    return result


def _terminal_expect(records: list[dict[str, Any]], role: str) -> dict[str, Any]:
    snapshots = [r for r in records if r.get("kind") == "visible_snapshot"]
    terminal = next((r for r in reversed(snapshots) if r.get("message_type") == 5), None)
    if terminal is None or not isinstance(terminal.get("observation"), dict):
        raise RecordingError(f"{role}: missing terminal visible snapshot")
    observation = terminal["observation"]
    initial = next(
        (
            r.get("observation")
            for r in snapshots
            if r.get("message_type") == 40 and isinstance(r.get("observation"), dict)
        ),
        None,
    )
    result = {
        key: observation[key]
        for key in ("turn", "phase", "turn_player", "life_points")
        if key in observation
    }
    zones = observation.get("zones")
    if not _is_array(zones):
        raise RecordingError(f"{role}: terminal snapshot missing zones")
    wanted: list[dict[str, Any]] = []
    for zone in zones:
        if not _is_object(zone):
            continue
        previous = (
            _zone_lookup(initial, zone.get("player"), zone.get("name"))
            if _is_object(initial)
            else None
        )
        changed = previous is None or _zone_signature(previous) != _zone_signature(zone)
        public_nonempty = zone.get("name") in PUBLIC_ZONES and zone.get("count", 0) > 0
        if changed or public_nonempty:
            wanted.append(_zone_assertion(zone))
    if wanted:
        result["zones"] = wanted
    return result


def _pairs(
    records: list[dict[str, Any]],
    role: str,
    surrendered: bool = False,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    prompts: dict[int, dict[str, Any]] = {}
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in records:
        kind = record.get("kind")
        if kind == "prompt":
            prompt_id = record.get("prompt_id")
            if type(prompt_id) is not int or prompt_id in prompts:
                raise RecordingError(f"{role} seq {record['seq']}: invalid/duplicate prompt_id")
            prompts[prompt_id] = record
        elif kind == "response":
            prompt_id = record.get("prompt_id")
            if type(prompt_id) is not int:
                raise RecordingError(f"{role} seq {record['seq']}: invalid response prompt_id")
            prompt = prompts.pop(prompt_id, None)
            if prompt is None or prompt["seq"] >= record["seq"]:
                raise RecordingError(f"{role} seq {record['seq']}: unpaired response")
            result.append((prompt, record))
    if prompts:
        first = next(iter(prompts.values()))
        end = _single(records, "duel_end", role)
        last_response_seq = max(
            (r["seq"] for r in records if r.get("kind") == "response"), default=0
        )
        if (
            not surrendered
            or len(prompts) != 1
            or first["seq"] <= last_response_seq
            or first["seq"] >= end["seq"]
        ):
            raise RecordingError(f"{role} seq {first['seq']}: prompt without response")
    return result


def _winner(ends: dict[str, dict[str, Any]]) -> str:
    values = [ends[role].get("winner") for role in ROLES]
    if values[0] == values[1] and values[0] in (*ROLES, "draw"):
        return cast(str, values[0])
    raise RecordingError(f"duel_end winner mismatch or missing: {values}")


def _public_zones(observation: dict[str, Any], role: str) -> dict[tuple[str, str], dict[str, Any]]:
    zones = observation.get("zones")
    if not _is_array(zones):
        raise RecordingError(f"{role}: visible snapshot missing zones")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for zone in zones:
        if not _is_object(zone) or zone.get("name") not in PUBLIC_ZONES:
            continue
        player = zone.get("player")
        if player not in (0, 1):
            raise RecordingError(f"{role}: invalid public zone player {player!r}")
        owner = role if player == 0 else ("guest" if role == "host" else "host")
        result[(owner, zone["name"])] = zone
    if len(result) != 8:
        raise RecordingError(f"{role}: incomplete public zones")
    return result


def _check_public_pair(host: dict[str, Any], guest: dict[str, Any], label: str) -> None:
    a = host.get("observation")
    b = guest.get("observation")
    if not _is_object(a) or not _is_object(b):
        raise RecordingError(f"{label}: missing visible snapshot")
    if a.get("turn") != b.get("turn"):
        raise RecordingError(f"{label}: turn mismatch between clients")
    lp_a, lp_b = a.get("life_points"), b.get("life_points")
    if (
        not _is_array(lp_a)
        or not _is_array(lp_b)
        or len(lp_a) != 2
        or len(lp_b) != 2
        or lp_a != lp_b[::-1]
    ):
        raise RecordingError(f"{label}: life points differ between clients")
    zones_a = _public_zones(a, "host")
    zones_b = _public_zones(b, "guest")
    for key in zones_a:
        za, zb = zones_a[key], zones_b[key]
        if za.get("count") != zb.get("count"):
            raise RecordingError(f"{label}: public zone {key} count mismatch")
        cards_a, cards_b = za.get("cards"), zb.get("cards")
        if not _is_array(cards_a) or not _is_array(cards_b):
            raise RecordingError(f"{label}: public zone {key} missing cards")
        by_seq_a = {c.get("sequence"): c for c in cards_a if _is_object(c)}
        by_seq_b = {c.get("sequence"): c for c in cards_b if _is_object(c)}
        if key[1] == "banished":
            owner_cards, other_cards = (
                (by_seq_a, by_seq_b) if key[0] == "host" else (by_seq_b, by_seq_a)
            )
            other_zone = zb if key[0] == "host" else za
            hidden = owner_cards.keys() - other_cards.keys()
            if (
                not other_cards.keys() <= owner_cards.keys()
                or other_zone.get("hidden_count", 0) != len(hidden)
                or any(
                    not str(owner_cards[seq].get("position", "")).startswith("face_down")
                    for seq in hidden
                )
            ):
                raise RecordingError(f"{label}: public zone {key} visibility mismatch")
        elif by_seq_a.keys() != by_seq_b.keys():
            raise RecordingError(f"{label}: public zone {key} sequence mismatch")
        for seq in by_seq_a.keys() & by_seq_b.keys():
            ca, cb = by_seq_a[seq], by_seq_b[seq]
            if ca.get("position") != cb.get("position"):
                raise RecordingError(f"{label}: public zone {key}/{seq} position mismatch")
            public_identity = key[1] == "graveyard" or str(ca.get("position", "")).startswith(
                "face_up"
            )
            if public_identity and ("card_id" in ca) != ("card_id" in cb):
                raise RecordingError(f"{label}: public zone {key}/{seq} visibility mismatch")
            if "card_id" in ca and "card_id" in cb and ca["card_id"] != cb["card_id"]:
                raise RecordingError(f"{label}: public zone {key}/{seq} card mismatch")


def _check_mirrored_public_state(captures: dict[str, list[dict[str, Any]]]) -> None:
    for message_type, name in PUBLIC_ANCHORS.items():
        pairs = {
            role: [
                r
                for r in captures[role]
                if r.get("kind") == "visible_snapshot" and r.get("message_type") == message_type
            ]
            for role in ROLES
        }
        if len(pairs["host"]) != len(pairs["guest"]):
            raise RecordingError(f"{name}: shared public snapshot count differs")
        if message_type == 5 and not pairs["host"]:
            raise RecordingError("missing shared terminal MSG_WIN snapshots")
        for index, (host, guest) in enumerate(zip(pairs["host"], pairs["guest"], strict=True), 1):
            _check_public_pair(
                host, guest, f"{name} #{index} host:{host['seq']} guest:{guest['seq']}"
            )


def _card_name(card_id: Any, cards_db: Path) -> str:
    if card_id is None:
        return ""
    display_id = _card_id_text(card_id) if type(card_id) is int else str(card_id)
    if cards_db.is_file():
        try:
            with sqlite3.connect(cards_db) as connection:
                row = connection.execute(
                    "SELECT name FROM texts WHERE id = ?", (int(card_id),)
                ).fetchone()
            if row and isinstance(row[0], str) and row[0]:
                return f"《{row[0]}》（{display_id}）"
        except (sqlite3.Error, ValueError, TypeError):
            pass
    return f"卡片 {display_id}"


def _visible_card_counts(cards: Any) -> Counter[int]:
    counts: Counter[int] = Counter()
    if _is_array(cards):
        for card in cards:
            if _is_object(card) and type(card.get("card_id")) is int:
                counts[card["card_id"]] += 1
    return counts


def _public_change_summary(
    previous: dict[str, Any] | None, current: dict[str, Any], cards_db: Path
) -> str:
    """Describe changes visible between prompts, without attributing them to an action."""
    if previous is None:
        return ""
    changes: list[str] = []
    before_lp, after_lp = previous.get("life_points"), current.get("life_points")
    if _is_array(before_lp) and _is_array(after_lp) and len(before_lp) == len(after_lp) == 2:
        for player, (before, after) in enumerate(zip(before_lp, after_lp, strict=True)):
            if type(before) is int and type(after) is int and before != after:
                changes.append(f"玩家{player} LP {before}→{after}")
    zones = current.get("zones")
    if not _is_array(zones):
        return "；".join(changes)
    for zone in zones:
        if not _is_object(zone):
            continue
        player, name = zone.get("player"), zone.get("name")
        if type(player) is not int or not isinstance(name, str) or name not in PUBLIC_ZONES:
            continue
        before = _zone_lookup(previous, player, name)
        if before is None or _zone_signature(before) == _zone_signature(zone):
            continue
        old_count, new_count = before.get("count"), zone.get("count")
        detail = f"{old_count}→{new_count}" if old_count != new_count else "内容或表示变化"
        old_cards, new_cards = before.get("cards"), zone.get("cards")
        old_ids = _visible_card_counts(old_cards)
        new_ids = _visible_card_counts(new_cards)
        added = new_ids - old_ids
        if added:
            names = "、".join(
                f"{_card_name(card_id, cards_db)}×{count}"
                if count > 1
                else _card_name(card_id, cards_db)
                for card_id, count in added.items()
            )
            detail += f"，新增 {names}"
        changes.append(f"玩家{player}{ZONE_LABELS[name]} {detail}")
    return "；".join(changes)


def _compile(
    source: Path,
    output: Path,
    cards_db: Path,
    overrides: dict[str, dict[str, Any]],
    analysis_draft: bool,
    scenario_kind: str,
) -> dict[str, Any]:
    captures = {role: _records(source / f"{role}.jsonl", role) for role in ROLES}
    sessions = {role: _single(captures[role], "session", role) for role in ROLES}
    ids = [sessions[role].get("record_id") for role in ROLES]
    if not ids[0] or ids[0] != ids[1]:
        raise RecordingError(f"session record_id mismatch: {ids}")
    decks: dict[str, str] = {}
    room_settings: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for role in ROLES:
        records = captures[role]
        room = _single(records, "room_joined", role)
        if room.get("mode") != 0:
            raise RecordingError(f"{role} seq {room['seq']}: require single 1v1")
        if room.get("no_shuffle_deck") not in (True, 1):
            reason = f"{role} seq {room['seq']}: deck shuffle was enabled"
            if not analysis_draft:
                raise RecordingError(reason)
            blockers.append(reason)
        for field, expected in (
            ("start_hand", 5),
            ("start_lp", 8000),
            ("draw_count", 1),
            ("time_limit", 0),
        ):
            if field in room and room[field] != expected:
                raise RecordingError(
                    f"{role} seq {room['seq']}: {field}={room[field]} "
                    f"differs from replay {expected}"
                )
        room_settings[role] = {
            key: value
            for key, value in room.items()
            if key not in ("kind", "seq", "role", "timestamp_unix_ms")
        }
        starts = _single(records, "duel_start", role)
        if room["seq"] >= starts["seq"]:
            raise RecordingError(f"{role}: room_joined must precede duel_start")
        submissions = [
            r for r in records if r.get("kind") == "deck_submitted" and r["seq"] < starts["seq"]
        ]
        if not submissions:
            raise RecordingError(f"{role}: no deck submitted before duel_start")
        submitted = submissions[-1]
        decks[role] = _deck(submitted, role)
        ended = _single(records, "duel_end", role)
        if ended["seq"] <= starts["seq"]:
            raise RecordingError(f"{role}: duel_end precedes duel_start")
        for record in records:
            if record.get("kind") == "error":
                raise RecordingError(
                    f"{role} seq {record['seq']}: recorder error "
                    f"{record.get('code')}: {record.get('message', '')}"
                )
            if record.get("kind") == "diagnostic_log_truncated":
                raise RecordingError(f"{role} seq {record['seq']}: capture truncated")
            if record.get("kind") == "visible_snapshot":
                message = record.get("message_type")
                if message in RANDOM_MESSAGES and message != 33:
                    reason = (
                        f"{role} seq {record['seq']}: uncontrolled random event "
                        f"{RANDOM_MESSAGES[message]}"
                    )
                    if scenario_kind == "random":
                        continue
                    if not analysis_draft:
                        raise RecordingError(reason)
                    blockers.append(reason)
    random_by_role = {
        role: [
            r.get("message_type")
            for r in captures[role]
            if r.get("kind") == "visible_snapshot" and r.get("message_type") in (36, 81, 130, 131)
        ]
        for role in ROLES
    }
    random_target: int | None = None
    if scenario_kind == "random":
        for role, messages in random_by_role.items():
            if len(messages) != 1:
                raise RecordingError(
                    f"{role}: random scenario requires exactly one target random operation; "
                    f"observed {messages}"
                )
        if random_by_role["host"] != random_by_role["guest"]:
            raise RecordingError(f"random message differs by perspective: {random_by_role}")
        random_target = random_by_role["host"][0]
    if room_settings["host"] != room_settings["guest"]:
        raise RecordingError("host and guest room settings differ")
    _check_mirrored_public_state(captures)
    ends = {role: _single(captures[role], "duel_end", role) for role in ROLES}
    winner = _winner(ends)
    surrendered = [r for role in ROLES for r in captures[role] if r.get("kind") == "surrender"]
    if len(surrendered) > 1:
        raise RecordingError("multiple surrender records")
    if surrendered and winner != ("guest" if surrendered[0]["role"] == "host" else "host"):
        raise RecordingError("surrender winner disagrees with duel_end")
    surrender_role = surrendered[0]["role"] if surrendered else None
    ordinal_usages: list[dict[str, Any]] = []
    used_overrides: set[str] = set()
    steps: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    rps: dict[str, list[str]] = {role: [] for role in ROLES}
    first_player: str | None = None
    place_steps: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    step_sources: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {
        role: [] for role in ROLES
    }
    timeline: dict[str, list[str]] = {role: [] for role in ROLES}
    timeline_slots: dict[str, list[int]] = {role: [] for role in ROLES}
    for role in ROLES:
        for prompt_record, response in _pairs(captures[role], role, bool(surrendered)):
            prompt = prompt_record.get("prompt")
            observation = prompt_record.get("observation")
            if not _is_object(prompt) or not _is_object(observation):
                raise RecordingError(
                    f"{role} seq {prompt_record['seq']}: missing prompt/observation"
                )
            action = _action(prompt, response, role, overrides, used_overrides, ordinal_usages)
            prompt_kind = prompt.get("kind")
            if prompt_kind in ("rock_paper_scissors", "first_player"):
                if action.get("kind") != "choice":
                    raise RecordingError(f"{role} seq {response['seq']}: invalid pregame action")
                selected = cast(dict[str, Any], action["match"]).get("kind")
                if prompt_kind == "rock_paper_scissors":
                    if selected not in ("rock", "paper", "scissors"):
                        raise RecordingError(f"{role} seq {response['seq']}: invalid hand")
                    rps[role].append(selected)
                    timeline[role].append(
                        f"- 赛前提示 #{prompt_record['seq']} → 响应 #{response['seq']}：{selected}"
                    )
                else:
                    if first_player is not None or selected not in ("go_first", "go_second"):
                        raise RecordingError(
                            f"{role} seq {response['seq']}: invalid first-player choice"
                        )
                    first_player = selected
                    timeline[role].append(
                        f"- 先后攻提示 #{prompt_record['seq']} → "
                        f"响应 #{response['seq']}：{selected}"
                    )
                continue
            step = {"expect": {}, "action": action}
            steps[role].append(step)
            step_sources[role].append((step, prompt, observation))
            if action["kind"] == "select_places":
                place_steps.append((role, prompt, response, action))
            candidate = action.get("match", {})
            label = (
                candidate.get("kind", action["kind"]) if _is_object(candidate) else action["kind"]
            )
            card = candidate.get("card_id") if _is_object(candidate) else None
            declined = prompt_kind == "chain" and label == "pass"
            action_text = "有可发动候选，选择不发动" if declined else f"选择 {label}"
            context = "，".join(
                f"{title} {observation[field]}"
                for field, title in (
                    ("turn", "回合"),
                    ("phase", "阶段"),
                    ("turn_player", "行动玩家"),
                )
                if field in observation
            )
            timeline_slots[role].append(len(timeline[role]))
            timeline[role].append(
                f"- 提示 #{prompt_record['seq']} → 响应 #{response['seq']}："
                + (f"{context}；" if context else "")
                + f"{prompt_kind}，{action_text}"
                + (f"（{_card_name(card, cards_db)}）" if card else "")
            )
    if not rps["host"] or not rps["guest"] or first_player is None:
        raise RecordingError("missing pregame decisions")
    if len(rps["host"]) != len(rps["guest"]):
        raise RecordingError("pregame rock-paper-scissors rounds differ")
    host_hand, guest_hand = rps["host"][-1], rps["guest"][-1]
    winning = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    if host_hand == guest_hand:
        raise RecordingError("pregame has no decisive final round")
    rps_winner = "host" if (host_hand, guest_hand) in winning else "guest"
    first_player_role = (
        rps_winner if first_player == "go_first" else ("guest" if rps_winner == "host" else "host")
    )
    for role, prompt, response, action in place_steps:
        controller_space = response.get("controller_space", sessions[role].get("controller_space"))
        action["places"] = _normalize_places(
            role, prompt, response, first_player_role, controller_space
        )
    for role in ROLES:
        previous: dict[str, Any] | None = None
        for index, (step, prompt, observation) in enumerate(step_sources[role]):
            step["expect"] = _expect(prompt, observation, step["action"], previous)
            if summary := _public_change_summary(previous, observation, cards_db):
                slot = timeline_slots[role][index]
                timeline[role][slot] += f"；自上一提示以来：{summary}"
            previous = observation
    for role in ROLES:
        timeline[role].append(f"- 终局 #{ends[role]['seq']}：胜者 {winner}")
    scene: dict[str, Any] = {
        "schema_version": 2 if scenario_kind == "random" else 1,
        "decks": {role: f"{role}.ydk" for role in ROLES},
        "pregame": {"host": rps["host"], "guest": rps["guest"], "winner_chooses": first_player},
        "steps": steps,
        "goal": {
            "kind": "duel_end",
            "winner": winner,
            "expect": {role: _terminal_expect(captures[role], role) for role in ROLES},
        },
    }
    if scenario_kind == "random":
        # A full recording cannot identify the effect-completion boundary. Keep
        # its decisions for review, but never label this generated file runnable.
        scene["scenario_kind"] = "random"
        scene["random_target"] = {
            "message_type": random_target,
            "max_runs": 20,
            "coverage": [],
        }
        blockers.append(
            "review required: truncate decisions at the completed effect, replace "
            "duel_end with a visible checkpoint, and specify per-result assertions"
        )
    if any(
        r.get("kind") == "visible_snapshot" and r.get("message_type") == 33
        for role in ROLES
        for r in captures[role]
    ):
        scene["allowed_random_events"] = ["hand_shuffle"]
    if surrendered:
        surrender = surrendered[0]
        expectations: dict[str, dict[str, Any]] = {}
        for role in ROLES:
            earlier = [
                r
                for r in captures[role]
                if r.get("kind") == "visible_snapshot"
                and (r["seq"] < surrender["seq"] if role == surrender_role else False)
            ]
            obs = earlier[-1].get("observation") if earlier else None
            expectations[role] = (
                {k: obs[k] for k in ("turn", "phase", "turn_player") if k in obs}
                if _is_object(obs)
                else {}
            )
        scene["goal"]["surrender"] = {"role": surrender["role"], "expect": expectations}
    if unused := overrides.keys() - used_overrides:
        raise RecordingError(f"unused or stale overrides: {sorted(unused)}")
    if scenario_kind != "random":
        try:
            Scenario(scene)
        except ScenarioError as exc:
            raise RecordingError(f"generated scenario invalid: {exc}") from exc
    for role in ROLES:
        (output / f"{role}.ydk").write_text(decks[role], encoding="utf-8")
    scenario_name = "scenario.unverified.yaml" if blockers else "scenario.yaml"
    (output / scenario_name).write_text(
        yaml.dump(scene, Dumper=_ScenarioDumper, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (output / "timeline.md").write_text(
        "# 双端对局时间线\n\n"
        + "\n\n".join(f"## {role}\n\n" + "\n".join(timeline[role]) for role in ROLES)
        + "\n",
        encoding="utf-8",
    )
    return {
        "status": "draft_unverified" if blockers else "compiled",
        "record_id": ids[0],
        "winner": winner,
        "steps": {role: len(steps[role]) for role in ROLES},
        "blockers": blockers,
        "scenario_kind": scenario_kind,
        "random_target_message_type": random_target,
        "ordinal_usages": ordinal_usages,
        "errors": [],
    }


def compile_recording(
    source: Path,
    output: Path,
    cards_db: Path | None = None,
    overrides_path: Path | None = None,
    analysis_draft: bool = False,
    scenario_kind: str = "deterministic",
) -> dict[str, Any]:
    """Write a scenario draft and report; replay must promote it to verified."""
    output.mkdir(parents=True, exist_ok=True)
    try:
        if scenario_kind not in ("deterministic", "random"):
            raise RecordingError(f"invalid scenario kind {scenario_kind!r}")
        override_file = overrides_path or source / "overrides.json"
        if overrides_path is not None and not overrides_path.is_file():
            raise RecordingError(f"missing override file: {overrides_path}")
        report = _compile(
            source,
            output,
            cards_db or Path(__file__).resolve().parents[3] / "cards.cdb",
            _overrides(override_file),
            analysis_draft,
            scenario_kind,
        )
        (output / "review-needed.json").unlink(missing_ok=True)
        stale = (
            "scenario.yaml"
            if report["status"] == "draft_unverified"
            else "scenario.unverified.yaml"
        )
        (output / stale).unlink(missing_ok=True)
    except (RecordingError, OSError, KeyError, TypeError, ValueError) as exc:
        report = {"status": "incomplete", "errors": [str(exc)]}
    (output / "compile-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
