"""Strict validation of known decision fields in v1 and v2 envelopes.

Composite constraint profile: min_count/max_count (or count), candidate mandatory; tribute uses
candidate.weight and min_weight/max_weight; sum uses target and candidate.value_options
(one or two positive alternatives); sort requires every candidate exactly once;
places uses allowed_places and count; counters uses total_count and candidate.max_count;
announce_card uses allowed_card_ids. Unknown constraint semantics fail closed.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from typing import cast

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]
type Object = dict[str, JSON]


class ContractError(ValueError):
    """An invalid request, intent, or action."""

    code = "invalid_intent"


class UnsupportedPrompt(ContractError):
    """Insufficient or unsupported constraint information; never guess."""

    code = "unsupported_prompt"


@dataclass(frozen=True)
class DecisionRequest:
    """Validated, detached copy of the request. Candidate IDs are prompt-scoped."""

    data: Object

    @property
    def prompt(self) -> Object:
        return cast(Object, self.data["prompt"])

    @property
    def candidates(self) -> list[Object]:
        return cast(list[Object], self.prompt["candidates"])


def _object(value: object, path: str) -> Object:
    if not isinstance(value, dict):
        raise ContractError(f"{path}: expected object with string keys")
    if any(not isinstance(k, str) for k in cast(dict[object, object], value)):
        raise ContractError(f"{path}: expected object with string keys")
    return cast(Object, value)


def _array(value: object, path: str) -> list[JSON]:
    if not isinstance(value, list):
        raise ContractError(f"{path}: expected array")
    return cast(list[JSON], value)


def _string(value: object, path: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise ContractError(f"{path}: expected {'possibly empty ' if empty else ''}string")
    return value


def _int(value: object, path: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ContractError(f"{path}: integer outside permitted range")
    return value


def _keys(obj: Object, required: set[str], allowed: set[str], path: str) -> None:
    if missing := required - obj.keys():
        raise ContractError(f"{path}: missing {sorted(missing)}")
    if extra := obj.keys() - allowed:
        raise ContractError(f"{path}: unknown fields {sorted(extra)}")


def _place(value: object) -> Object:
    place = _object(value, "place")
    _keys(
        place,
        {"controller", "location", "sequence"},
        {"controller", "location", "sequence"},
        "place",
    )
    _int(place["controller"], "place.controller", maximum=1)
    if place["location"] not in ("monster", "spell", "mzone", "szone"):
        raise ContractError("place.location: expected field location")
    _int(place["sequence"], "place.sequence", maximum=7)
    return place


def _card(value: object) -> None:
    card = _object(value, "card")
    for key in ("instance_id", "location"):
        _string(card.get(key), f"card.{key}")
    _int(card.get("controller"), "card.controller", maximum=1)
    if "sequence" in card:
        _int(card["sequence"], "card.sequence")
    elif card["location"] != "graveyard":
        raise ContractError("card.sequence: required outside restricted graveyard selections")
    if "card_id" in card:
        _int(card["card_id"], "card.card_id", 1, 0xFFFFFFFF)
    if "public" in card:
        if type(card["public"]) is not bool:
            raise ContractError("card.public: expected boolean")
        if card["public"] is False and "card_id" in card:
            raise ContractError("unpublished card must not include card_id")


def _json_value(value: object) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in cast(list[object], value):
            _json_value(item)
        return
    if isinstance(value, dict):
        for key, item in cast(dict[object, object], value).items():
            if not isinstance(key, str):
                raise ContractError("JSON object keys must be strings")
            _json_value(item)
        return
    raise ContractError("document must contain only finite JSON values")


def _decode(value: object) -> Object:
    if isinstance(value, (str, bytes)):

        def pairs(items: list[tuple[str, JSON]]) -> Object:
            result: Object = {}
            for key, item in items:
                if key in result:
                    raise ContractError(f"duplicate JSON key: {key}")
                result[key] = item
            return result

        def invalid_constant(value: str) -> JSON:
            raise ContractError(f"invalid JSON constant: {value}")

        try:
            value = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        except (ValueError, UnicodeError) as exc:
            raise ContractError(f"invalid JSON: {exc}") from exc
    result = _object(value, "document")
    _json_value(result)
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ContractError("document must contain finite JSON values") from exc
    return copy.deepcopy(result)


def parse_request(value: object) -> DecisionRequest:
    """Validate a JSON string/bytes or mapping; additive envelope fields are allowed."""
    data = _decode(value)
    if type(data.get("schema_version")) is not int or data["schema_version"] not in (1, 2):
        raise ContractError("unsupported schema_version")
    if data["schema_version"] == 2:
        _int(data.get("state_version"), "state_version", 1)
        if type(data.get("history_complete")) is not bool:
            raise ContractError("history_complete: expected boolean")
        if data["history_complete"] is not True:
            raise ContractError("history_incomplete")
    for key in ("session_id", "duel_id"):
        _string(data.get(key), key)
    _int(data.get("prompt_id"), "prompt_id", 1)
    digest = _string(data.get("database_sha256"), "database_sha256")
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ContractError("database_sha256: expected lowercase SHA256")
    if "deadline_unix_ms" not in data:
        raise ContractError("missing deadline_unix_ms")
    if data["deadline_unix_ms"] is not None:
        _int(data["deadline_unix_ms"], "deadline_unix_ms")
    observation = _object(data.get("observation"), "observation")
    for key in ("self_player", "turn_player"):
        _int(observation.get(key), key, maximum=1)
    _int(observation.get("turn"), "turn")
    _string(observation.get("phase"), "phase")
    points = _array(observation.get("life_points"), "life_points")
    if len(points) != 2:
        raise ContractError("life_points must contain two values")
    for point in points:
        _int(point, "life_points")
    for key in ("zones", "events"):
        for item in _array(observation.get(key), key):
            obj = _object(item, key)
            if key == "events" and data["schema_version"] == 2:
                _int(obj.get("event_id"), "event.event_id", 1)
                _string(obj.get("kind"), "event.kind")
            if "card" in obj and (key == "zones" or data["schema_version"] == 1):
                _card(obj["card"])
            if "cards" in obj and (key == "zones" or data["schema_version"] == 1):
                for card in _array(obj["cards"], f"{key}.cards"):
                    _card(card)
    prompt = _object(data.get("prompt"), "prompt")
    _string(prompt.get("kind"), "prompt.kind")
    _string(prompt.get("description"), "prompt.description", empty=True)
    _object(prompt.get("constraints"), "constraints")
    seen: set[str] = set()
    for item in _array(prompt.get("candidates"), "candidates"):
        candidate = _object(item, "candidate")
        cid = _string(candidate.get("id"), "candidate.id")
        if cid in seen:
            raise ContractError(f"duplicate candidate ID: {cid}")
        seen.add(cid)
        _string(candidate.get("kind"), "candidate.kind")
        _string(candidate.get("description"), "candidate.description", empty=True)
        if "card" in candidate:
            _card(candidate["card"])
    return DecisionRequest(data)


def match_candidates(request: DecisionRequest, selector: object) -> list[str]:
    """Match exact known fields; return all IDs so callers can detect ambiguity."""
    query = _object(selector, "selector")
    allowed = {"id", "kind", "card_id", "instance_id", "controller", "location", "sequence"}
    _keys(query, set(), allowed, "selector")
    if not query:
        raise ContractError("selector must not be empty")
    for key, value in query.items():
        if key in ("card_id", "controller", "sequence"):
            _int(value, key, 1 if key == "card_id" else 0, 1 if key == "controller" else None)
        else:
            _string(value, key)
    matches: list[str] = []
    for candidate in request.candidates:
        card = cast(Object, candidate.get("card", {}))
        if all((candidate if k in ("id", "kind") else card).get(k) == v for k, v in query.items()):
            matches.append(cast(str, candidate["id"]))
    return matches


def _ids(value: object, candidates: dict[str, Object]) -> list[str]:
    ids = [_string(item, "candidate_ids") for item in _array(value, "candidate_ids")]
    if len(set(ids)) != len(ids):
        raise ContractError("duplicate candidate IDs")
    if any(cid not in candidates for cid in ids):
        raise ContractError("unknown candidate ID")
    return ids


def _count(count: int, constraints: Object) -> None:
    if "count" in constraints:
        minimum = maximum = _int(constraints["count"], "count")
        if "min_count" in constraints or "max_count" in constraints:
            raise UnsupportedPrompt("count and min_count/max_count cannot coexist")
    elif "min_count" in constraints and "max_count" in constraints:
        minimum = _int(constraints["min_count"], "min_count")
        maximum = _int(constraints["max_count"], "max_count", minimum)
    else:
        raise UnsupportedPrompt("missing count or min_count/max_count constraints")
    if not minimum <= count <= maximum:
        raise ContractError("selection count outside permitted range")


def _constraints(constraints: Object, allowed: set[str]) -> None:
    if "cancelable" in constraints and type(constraints["cancelable"]) is not bool:
        raise ContractError("cancelable must be boolean")
    if extra := constraints.keys() - allowed:
        raise UnsupportedPrompt(f"unsupported constraints: {sorted(extra)}")


def validate_action(request: DecisionRequest, value: object) -> Object:
    """Validate and return a detached action; never return protocol bytes."""
    action = _decode(value)
    kind = _string(action.get("kind"), "action.kind")
    prompt_kind = cast(str, request.prompt["kind"])
    constraints = cast(Object, request.prompt["constraints"])
    candidates = {cast(str, c["id"]): c for c in request.candidates}
    choice_prompts = {
        "idle_command",
        "battle_command",
        "yes_no",
        "effect_yes_no",
        "option",
        "chain",
        "position",
        "announce_number",
        "rock_paper_scissors",
        "first_player",
        "effect_yesno",
        "yesno",
    }
    if kind in ("choice", "select_step"):
        _keys(action, {"kind", "candidate_id"}, {"kind", "candidate_id"}, "action")
        cid = _ids([action["candidate_id"]], candidates)[0]
        candidate_kind = candidates[cid]["kind"]
        controls = {
            "select_card": {"cancel"},
            "select_cards": {"cancel"},
            "tribute": {"cancel"},
            "sort": {"default"},
            "unselect_card": {"cancel", "finish"},
            "select_unselect_card": {"cancel", "finish"},
        }
        control_choice = kind == "choice" and candidate_kind in controls.get(prompt_kind, set())
        if (kind == "choice" and prompt_kind not in choice_prompts and not control_choice) or (
            kind == "select_step" and prompt_kind not in ("unselect_card", "select_unselect_card")
        ):
            raise UnsupportedPrompt(f"{kind} unsupported for {prompt_kind}")
        allowed_constraints = {"cancelable"}
        if control_choice:
            allowed_constraints |= {"count", "min_count", "max_count"}
            if prompt_kind == "tribute":
                allowed_constraints |= {"min_weight", "max_weight"}
        _constraints(constraints, allowed_constraints)
        if candidate_kind == "cancel" and constraints.get("cancelable") is not True:
            raise ContractError("cancel candidate requires cancelable prompt")
    elif kind == "select_cards":
        if prompt_kind not in (
            "select_card",
            "select_cards",
            "tribute",
            "sum",
            "sort",
            "announce_race",
            "announce_attribute",
        ):
            raise UnsupportedPrompt(f"select_cards unsupported for {prompt_kind}")
        _keys(action, {"kind", "candidate_ids"}, {"kind", "candidate_ids"}, "action")
        ids = _ids(action["candidate_ids"], candidates)
        if len(ids) > 255:
            raise ContractError("card response exceeds protocol count limit")
        allowed_kind = (
            {"race"}
            if prompt_kind == "announce_race"
            else ({"attribute"} if prompt_kind == "announce_attribute" else {"card"})
        )
        if any(candidates[cid]["kind"] not in allowed_kind for cid in ids):
            raise ContractError("candidate kind does not belong to this composite selection")
        permitted = {"min_count", "max_count", "count", "cancelable"}
        if prompt_kind == "tribute":
            permitted |= {"min_weight", "max_weight"}
        if prompt_kind == "sum":
            permitted |= {"target", "mode"}
        _constraints(constraints, permitted)
        if any(candidates[cid]["kind"] in ("cancel", "default", "finish") for cid in ids):
            raise ContractError("control candidate cannot appear in a card selection")
        if prompt_kind == "sort":
            card_ids = {cid for cid, candidate in candidates.items() if candidate["kind"] == "card"}
            if set(ids) != card_ids:
                raise ContractError("sort must include every card candidate")
            _count(len(ids), constraints)
        else:
            _count(len(ids), constraints)
        mandatory: list[str] = []
        for cid, candidate in candidates.items():
            if "mandatory" in candidate:
                if type(candidate["mandatory"]) is not bool:
                    raise ContractError("mandatory must be boolean")
                if candidate["mandatory"]:
                    mandatory.append(cid)
        if not set(mandatory) <= set(ids):
            raise ContractError("missing mandatory candidate")
        if prompt_kind in ("announce_race", "announce_attribute"):
            bits: list[int] = []
            for candidate in candidates.values():
                if "bit" not in candidate:
                    raise UnsupportedPrompt("announcement candidates require bit values")
                bit = _int(candidate["bit"], "bit", 1)
                if bit & (bit - 1):
                    raise ContractError("announcement bit must be a power of two")
                bits.append(bit)
            if len(set(bits)) != len(bits):
                raise ContractError("duplicate announcement bits")
        if prompt_kind == "tribute":
            if "min_weight" not in constraints:
                raise UnsupportedPrompt("missing tribute weights")
            if any("weight" not in candidates[cid] for cid in ids):
                raise UnsupportedPrompt("missing candidate tribute weight")
            total = sum(_int(candidates[cid]["weight"], "weight") for cid in ids)
            lo = _int(constraints["min_weight"], "min_weight")
            if "max_weight" in constraints:
                _int(constraints["max_weight"], "max_weight")
            if total < lo:
                raise ContractError("tribute weight outside permitted range")
        if prompt_kind == "sum":
            if "target" not in constraints:
                raise UnsupportedPrompt("missing sum target")
            target = _int(constraints["target"], "target")
            mode = constraints.get("mode")
            if mode not in ("exact", "at_least"):
                raise UnsupportedPrompt("sum mode must be exact or at_least")
            if not ids:
                raise ContractError("sum requires at least one material")
            options: list[list[int]] = []
            for cid in ids:
                if "value_options" not in candidates[cid]:
                    raise UnsupportedPrompt("missing sum weights")
                weights = _array(candidates[cid]["value_options"], "value_options")
                if not 1 <= len(weights) <= 2:
                    raise UnsupportedPrompt("sum requires one or two weights per candidate")
                options.append([_int(w, "weight") for w in weights])
            if mode == "at_least":
                lows = [min(values) for values in options]
                if (
                    sum(max(values) for values in options) < target
                    or sum(lows) - min(lows) >= target
                ):
                    raise ContractError("selected materials violate at_least sum constraint")
            else:
                reachable = {0}
                work = 0
                for values in options:
                    next_values: set[int] = set()
                    for total in reachable:
                        for weight in values:
                            work += 1
                            if work > 1_000_000:
                                raise UnsupportedPrompt("sum validation work limit exceeded")
                            if weight > 0 and total + weight <= target:
                                next_values.add(total + weight)
                    reachable = next_values
                if target not in reachable:
                    raise ContractError("selected cards cannot meet sum target")
    elif kind == "select_places":
        if prompt_kind not in ("place", "select_place", "disfield"):
            raise UnsupportedPrompt(f"select_places unsupported for {prompt_kind}")
        _keys(action, {"kind", "places"}, {"kind", "places"}, "action")
        _constraints(constraints, {"count", "min_count", "max_count", "cancelable"})
        places = [_place(p) for p in _array(action["places"], "places")]
        _count(len(places), constraints)
        allowed = [
            _place({key: c[key] for key in ("controller", "location", "sequence")})
            for c in request.candidates
            if {"controller", "location", "sequence"} <= c.keys()
        ]
        if len(allowed) != len(request.candidates):
            raise UnsupportedPrompt("place candidates require explicit coordinates")
        keys = [json.dumps(p, sort_keys=True) for p in places]
        if len(set(keys)) != len(keys) or any(p not in allowed for p in places):
            raise ContractError("duplicate or forbidden place")
    elif kind == "distribute_counters":
        if prompt_kind not in ("counter", "select_counter"):
            raise UnsupportedPrompt(f"distribute_counters unsupported for {prompt_kind}")
        _keys(action, {"kind", "allocations"}, {"kind", "allocations"}, "action")
        _constraints(constraints, {"total_count"})
        if "total_count" not in constraints:
            raise UnsupportedPrompt("missing counter total")
        allocation_ids: list[JSON] = []
        total = 0
        for item in _array(action["allocations"], "allocations"):
            allocation = _object(item, "allocation")
            _keys(allocation, {"candidate_id", "count"}, {"candidate_id", "count"}, "allocation")
            cid = _string(allocation["candidate_id"], "candidate_id")
            _ids([cid], candidates)
            allocation_ids.append(cid)
            if "max_count" not in candidates[cid]:
                raise UnsupportedPrompt("missing counter capacity")
            count = _int(allocation["count"], "count")
            if count > _int(candidates[cid]["max_count"], "max_count"):
                raise ContractError("counter capacity exceeded")
            total += count
        _ids(allocation_ids, candidates)
        if total != _int(constraints["total_count"], "total_count"):
            raise ContractError("counter total mismatch")
    elif kind == "announce_card":
        if prompt_kind != "announce_card":
            raise UnsupportedPrompt(f"announce_card unsupported for {prompt_kind}")
        _keys(action, {"kind", "card_id"}, {"kind", "card_id"}, "action")
        card_id = _int(action["card_id"], "card_id", 1, 0xFFFFFFFF)
        _constraints(constraints, {"allowed_card_ids"})
        if "allowed_card_ids" not in constraints:
            raise UnsupportedPrompt("announce filter requires resolved allowed_card_ids")
        allowed_cards = [
            _int(c, "allowed_card_ids", 1, 0xFFFFFFFF)
            for c in _array(constraints["allowed_card_ids"], "allowed_card_ids")
        ]
        if card_id not in allowed_cards:
            raise ContractError("card excluded by announce filter")
    else:
        raise UnsupportedPrompt(f"unsupported action kind: {kind}")
    return action


def translate_intent(request: DecisionRequest, value: object) -> Object:
    """Accept a validated action or choice/select_step with an exact match selector."""
    intent = _decode(value)
    if "selector" not in intent:
        return validate_action(request, intent)
    _keys(intent, {"kind", "selector"}, {"kind", "selector"}, "intent")
    if intent["kind"] not in ("choice", "select_step"):
        raise ContractError("selector intent requires choice or select_step")
    matches = match_candidates(request, intent["selector"])
    if len(matches) != 1:
        raise ContractError(f"selector matched {len(matches)} candidates; require exactly one")
    return validate_action(request, {"kind": intent["kind"], "candidate_id": matches[0]})


def build_response(request: DecisionRequest, intent: object, reason: str) -> Object:
    """Translate an intent and copy the exact request correlation fields."""
    _string(reason, "reason", empty=True)
    response = {
        key: request.data[key] for key in ("schema_version", "session_id", "duel_id", "prompt_id")
    }
    if request.data["schema_version"] == 2:
        response["state_version"] = request.data["state_version"]
        events = cast(list[Object], cast(Object, request.data["observation"])["events"])
        response["ack_event_id"] = events[-1]["event_id"] if events else 0
    response["reason"] = reason
    response["action"] = translate_intent(request, intent)
    return response


def validate_response(request: DecisionRequest, value: object) -> Object:
    """Validate response envelope, correlation fields, and semantic action."""
    response = _decode(value)
    for key in ("schema_version", "session_id", "duel_id", "prompt_id"):
        if (
            type(response.get(key)) is not type(request.data[key])
            or response.get(key) != request.data[key]
        ):
            raise ContractError(f"stale or invalid response {key}")
    if request.data["schema_version"] == 2:
        if response.get("state_version") != request.data["state_version"]:
            raise ContractError("stale or invalid response state_version")
        ack = _int(response.get("ack_event_id"), "ack_event_id")
        events = cast(list[Object], cast(Object, request.data["observation"])["events"])
        if events and ack < cast(int, events[-1]["event_id"]):
            raise ContractError("response does not acknowledge request events")
    _string(response.get("reason"), "reason", empty=True)
    response["action"] = validate_action(request, response.get("action"))
    return response
