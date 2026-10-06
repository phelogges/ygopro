"""Strict, visible-state-only scripted duel decisions.

Scenario files are authoring fixtures, not a protocol between the clients and the agent.
They never carry raw CTOS bytes or prompt-scoped candidate IDs.
"""

from __future__ import annotations

import copy
from pathlib import Path
from time import time
from typing import Any, cast

import yaml  # pyright: ignore[reportMissingModuleSource]

from .contract import ContractError, DecisionRequest, Object, build_response, parse_request

ROLES = ("host", "guest")
CARD_FIELDS = {
    "card_id",
    "controller",
    "location",
    "sequence",
    "position",
    "attack",
    "defense",
    "level",
    "rank",
    "link",
    "owner",
}
SELECTOR_FIELDS = {
    "kind",
    "description",
    "description_id",
    "effect_flag",
    "number",
    "bit",
    "weight",
    "card_id",
    "instance_id",
    "controller",
    "location",
    "sequence",
    "position",
    "attack",
    "defense",
    "level",
    "rank",
    "link",
    "owner",
    "ordinal",
    "expected_matches",
}
OPTIONAL_DECLINE_KINDS = {"chain": "pass", "effect_yes_no": "decline", "yes_no": "decline"}


class ScenarioError(ValueError):
    """Invalid fixture or first divergence from its expected duel trace."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict[str, Any]:
    result: dict[str, Any] = {}
    loader_any: Any = loader
    for key_node, value_node in node.value:
        key: Any = loader_any.construct_object(key_node)
        if not isinstance(key, str):
            raise ScenarioError(
                f"YAML mapping key must be a string at line {key_node.start_mark.line + 1}"
            )
        if key in result:
            raise ScenarioError(
                f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}"
            )
        result[key] = loader_any.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _dict(value: object, path: str, required: set[str], allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{path}: expected mapping with string keys")
    if any(not isinstance(k, str) for k in cast(dict[object, object], value)):
        raise ScenarioError(f"{path}: expected mapping with string keys")
    obj = cast(dict[str, Any], value)
    if missing := required - obj.keys():
        raise ScenarioError(f"{path}: missing {sorted(missing)}")
    if extra := obj.keys() - allowed:
        raise ScenarioError(f"{path}: unknown fields {sorted(extra)}")
    return obj


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScenarioError(f"{path}: expected list")
    return cast(list[Any], value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioError(f"{path}: expected nonempty string")
    return value


def _integer(value: object, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ScenarioError(f"{path}: expected integer >= {minimum}")
    return value


def _card_id(value: object, path: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ScenarioError(f"{path}: card_id must be a quoted decimal string")
    parsed = int(value)
    if not 1 <= parsed <= 0xFFFFFFFF:
        raise ScenarioError(f"{path}: card_id outside supported range")
    return parsed


def _normalize_card_id(obj: dict[str, Any], path: str, *, allow_int: bool = False) -> None:
    if "card_id" in obj:
        if allow_int and type(obj["card_id"]) is int and 1 <= obj["card_id"] <= 0xFFFFFFFF:
            return
        obj["card_id"] = _card_id(obj["card_id"], f"{path}.card_id")


def _selector(value: object, path: str) -> dict[str, Any]:
    obj = _dict(value, path, set(), SELECTOR_FIELDS)
    if not obj or set(obj) <= {"ordinal", "expected_matches"}:
        raise ScenarioError(f"{path}: selector requires semantic fields")
    _normalize_card_id(obj, path)
    for key in (
        "controller",
        "sequence",
        "ordinal",
        "expected_matches",
        "attack",
        "defense",
        "level",
        "rank",
        "link",
        "owner",
        "description_id",
        "effect_flag",
        "number",
        "bit",
        "weight",
    ):
        if key in obj:
            _integer(obj[key], f"{path}.{key}", 1 if key in ("ordinal", "expected_matches") else 0)
    if "ordinal" in obj and "expected_matches" not in obj:
        raise ScenarioError(f"{path}: ordinal requires expected_matches")
    if "ordinal" in obj and obj["ordinal"] > obj["expected_matches"]:
        raise ScenarioError(f"{path}: ordinal exceeds expected_matches")
    for key in ("kind", "description", "instance_id", "location"):
        if key in obj:
            _string(obj[key], f"{path}.{key}")
    if "position" in obj and not isinstance(obj["position"], (str, int)):
        raise ScenarioError(f"{path}.position: expected string or integer")
    return obj


def _assertion(value: object, path: str, *, normalized: bool = False) -> dict[str, Any]:
    obj = _dict(value, path, set(), {"turn", "phase", "turn_player", "life_points", "zones"})
    if "turn" in obj:
        _integer(obj["turn"], f"{path}.turn")
    if "turn_player" in obj and obj["turn_player"] not in (0, 1):
        raise ScenarioError(f"{path}.turn_player: expected 0 or 1")
    if "phase" in obj:
        _string(obj["phase"], f"{path}.phase")
    if "life_points" in obj:
        points = _list(obj["life_points"], f"{path}.life_points")
        if len(points) != 2:
            raise ScenarioError(f"{path}.life_points: expected two values")
        for i, point in enumerate(points):
            if point is not None:
                _integer(point, f"{path}.life_points[{i}]")
    for i, zone in enumerate(_list(obj.get("zones", []), f"{path}.zones")):
        zp = f"{path}.zones[{i}]"
        z = _dict(zone, zp, {"player", "name"}, {"player", "name", "count", "contains", "exact"})
        if z["player"] in ("self", "opponent"):
            z["player"] = 0 if z["player"] == "self" else 1
        if z["player"] not in (0, 1) or type(z["player"]) is bool:
            raise ScenarioError(f"{zp}.player: expected self, opponent, 0, or 1")
        _string(z["name"], f"{zp}.name")
        if "count" in z:
            _integer(z["count"], f"{zp}.count")
        if "contains" in z and "exact" in z:
            raise ScenarioError(f"{zp}: contains and exact cannot coexist")
        for key in ("contains", "exact"):
            if key in z:
                cards = _list(z[key], f"{zp}.{key}")
                for j, card in enumerate(cards):
                    cp = f"{zp}.{key}[{j}]"
                    c = _dict(card, cp, set(), CARD_FIELDS | {"count"})
                    if not (set(c) - {"count"}):
                        raise ScenarioError(f"{cp}: expected at least one card field")
                    _normalize_card_id(c, cp, allow_int=normalized)
                    if "count" in c:
                        _integer(c["count"], f"{cp}.count", 1)
                    for field in (
                        "controller",
                        "sequence",
                        "attack",
                        "defense",
                        "level",
                        "rank",
                        "link",
                        "owner",
                    ):
                        if field in c:
                            _integer(c[field], f"{cp}.{field}")
    return obj


def _action(value: object, path: str) -> dict[str, Any]:
    obj = _dict(
        value, path, {"kind"}, {"kind", "match", "matches", "places", "allocations", "card_id"}
    )
    kind = _string(obj["kind"], f"{path}.kind")
    field = {
        "choice": "match",
        "select_step": "match",
        "select_cards": "matches",
        "select_places": "places",
        "distribute_counters": "allocations",
        "announce_card": "card_id",
    }.get(kind)
    if field is None or set(obj) != {"kind", field}:
        raise ScenarioError(f"{path}: unsupported kind or incorrect fields for {kind}")
    if field == "match":
        _selector(obj[field], f"{path}.match")
    elif field == "matches":
        for i, item in enumerate(_list(obj[field], f"{path}.matches")):
            _selector(item, f"{path}.matches[{i}]")
    elif field == "places":
        for i, item in enumerate(_list(obj[field], f"{path}.places")):
            p = _dict(
                item,
                f"{path}.places[{i}]",
                {"controller", "location", "sequence"},
                {"controller", "location", "sequence"},
            )
            if p["controller"] not in (0, 1):
                raise ScenarioError(f"{path}.places[{i}].controller: expected 0 or 1")
            _string(p["location"], f"{path}.places[{i}].location")
            _integer(p["sequence"], f"{path}.places[{i}].sequence")
    elif field == "allocations":
        for i, item in enumerate(_list(obj[field], f"{path}.allocations")):
            a = _dict(item, f"{path}.allocations[{i}]", {"match", "count"}, {"match", "count"})
            _selector(a["match"], f"{path}.allocations[{i}].match")
            _integer(a["count"], f"{path}.allocations[{i}].count")
    elif field == "card_id":
        _normalize_card_id(obj, path)
    return obj


def _candidate_match(candidate: Object, selector: dict[str, Any]) -> bool:
    card = candidate.get("card")
    card_obj = cast(Object, card) if isinstance(card, dict) else {}
    for key, expected in selector.items():
        if key in ("ordinal", "expected_matches"):
            continue
        source = card_obj if key in CARD_FIELDS | {"instance_id"} else candidate
        if source.get(key) != expected:
            return False
    return True


def _zone_match(value: Any, wanted: dict[str, Any]) -> bool:
    return (
        isinstance(value, dict)
        and cast(dict[str, Any], value).get("player") == wanted["player"]
        and cast(dict[str, Any], value).get("name") == wanted["name"]
    )


def _card_match(value: Any, predicate: dict[str, Any]) -> bool:
    return isinstance(value, dict) and all(
        cast(dict[str, Any], value).get(key) == expected for key, expected in predicate.items()
    )


class Scenario:
    """One in-memory, fail-fast duel fixture with separate role cursors."""

    def __init__(self, data: dict[str, Any], source: Path | None = None):
        root = _dict(
            copy.deepcopy(data),
            "scenario",
            {"schema_version", "decks", "pregame", "steps", "goal"},
            {
                "schema_version",
                "decks",
                "pregame",
                "steps",
                "goal",
                "defaults",
                "allowed_random_events",
            },
        )
        if type(root["schema_version"]) is not int or root["schema_version"] != 1:
            raise ScenarioError("scenario.schema_version: expected 1")
        self.source = source
        defaults = _dict(root.get("defaults", {}), "defaults", set(), {"optional"})
        if "optional" in defaults and defaults["optional"] != "decline":
            raise ScenarioError("defaults.optional: expected decline")
        self._optional_decline = defaults.get("optional") == "decline"
        allowed_random_events = _list(
            root.get("allowed_random_events", []), "allowed_random_events"
        )
        if allowed_random_events not in ([], ["hand_shuffle"]):
            raise ScenarioError("allowed_random_events: only unique hand_shuffle is supported")
        self.allowed_random_messages: set[int] = (
            {33} if "hand_shuffle" in allowed_random_events else set()
        )
        self.ignored_decisions: list[dict[str, Any]] = []
        self.decks = _dict(root["decks"], "decks", set(ROLES), set(ROLES))
        for role in ROLES:
            _string(self.decks[role], f"decks.{role}")
        self.pregame = _dict(
            root["pregame"],
            "pregame",
            set(ROLES) | {"winner_chooses"},
            set(ROLES) | {"winner_chooses"},
        )
        for role in ROLES:
            hands = self.pregame[role]
            if isinstance(hands, str):
                hands = [hands]
            hands = _list(hands, f"pregame.{role}")
            if not hands or any(v not in ("rock", "paper", "scissors") for v in hands):
                raise ScenarioError(f"pregame.{role}: expected rock/paper/scissors sequence")
            self.pregame[role] = hands
        if self.pregame["winner_chooses"] not in ("go_first", "go_second"):
            raise ScenarioError("pregame.winner_chooses: expected go_first or go_second")
        self.steps = _dict(root["steps"], "steps", set(ROLES), set(ROLES))
        for role in ROLES:
            steps = _list(self.steps[role], f"steps.{role}")
            for i, step in enumerate(steps):
                path = f"steps.{role}[{i}]"
                s = _dict(step, path, {"expect", "action"}, {"expect", "action", "wait_for"})
                e = _dict(
                    s["expect"],
                    f"{path}.expect",
                    {"prompt"},
                    {"prompt", "turn", "phase", "turn_player", "life_points", "zones"},
                )
                _string(e["prompt"], f"{path}.expect.prompt")
                _assertion({k: v for k, v in e.items() if k != "prompt"}, f"{path}.expect")
                _action(s["action"], f"{path}.action")
                if "wait_for" in s:
                    check = _dict(
                        s["wait_for"],
                        f"{path}.wait_for",
                        {"timeout_ms", "expect"},
                        {"timeout_ms", "expect"},
                    )
                    _integer(check["timeout_ms"], f"{path}.wait_for.timeout_ms", 1)
                    _assertion(check["expect"], f"{path}.wait_for.expect")
        self.goal = _dict(root["goal"], "goal", {"kind"}, {"kind", "expect", "winner", "surrender"})
        if self.goal["kind"] == "checkpoint":
            _dict(self.goal, "goal", {"kind", "expect"}, {"kind", "expect"})
            targets = _dict(self.goal["expect"], "goal.expect", set(), set(ROLES))
            if not targets:
                raise ScenarioError("goal.expect: at least one role assertion required")
            for role in ROLES:
                targets.setdefault(role, {})
                _assertion(targets[role], f"goal.expect.{role}")
        elif self.goal["kind"] == "duel_end":
            _dict(self.goal, "goal", {"kind", "winner"}, {"kind", "winner", "surrender", "expect"})
            if self.goal["winner"] not in (*ROLES, "draw", "any"):
                raise ScenarioError("goal.winner: expected host, guest, draw, or any")
            if "expect" in self.goal:
                targets = _dict(self.goal["expect"], "goal.expect", set(ROLES), set(ROLES))
                for role in ROLES:
                    _assertion(targets[role], f"goal.expect.{role}")
            if "surrender" in self.goal:
                surrender = _dict(
                    self.goal["surrender"],
                    "goal.surrender",
                    {"role", "expect"},
                    {"role", "expect"},
                )
                surrender_role = surrender["role"]
                if surrender_role not in ROLES or self.goal["winner"] != (
                    "guest" if surrender_role == "host" else "host"
                ):
                    raise ScenarioError(
                        "goal.surrender: requires a duelist role and the other role as winner"
                    )
                expectations = _dict(
                    surrender["expect"], "goal.surrender.expect", set(ROLES), set(ROLES)
                )
                for role in ROLES:
                    _assertion(expectations[role], f"goal.surrender.expect.{role}")
        else:
            raise ScenarioError("goal.kind: expected checkpoint or duel_end")
        self._cursors = {role: 0 for role in ROLES}
        self._rps = {role: 0 for role in ROLES}
        self._first_player_seen = False
        self.wait_for: list[dict[str, Any]] = []
        if len(self.pregame["host"]) != len(self.pregame["guest"]):
            raise ScenarioError("pregame: host and guest rock-paper-scissors rounds differ")
        winner = None
        winning = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
        for i, (host, guest) in enumerate(
            zip(self.pregame["host"], self.pregame["guest"], strict=True)
        ):
            if host == guest:
                continue
            if i != len(self.pregame["host"]) - 1:
                raise ScenarioError("pregame: rounds after decisive rock-paper-scissors result")
            winner = "host" if (host, guest) in winning else "guest"
        if winner is None:
            raise ScenarioError("pregame: scripted rounds must end in a winner")
        self.rps_winner_role: str = winner
        self.first_player_role: str = (
            winner
            if self.pregame["winner_chooses"] == "go_first"
            else ("guest" if winner == "host" else "host")
        )

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        source = Path(path)
        try:
            data = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueLoader)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ScenarioError(f"{source}: {exc}") from exc
        if not isinstance(data, dict):
            raise ScenarioError(f"{source}: expected YAML mapping")
        return cls(cast(dict[str, Any], data), source)

    def remaining_steps(self) -> dict[str, int]:
        return {role: len(self.steps[role]) - self._cursors[role] for role in ROLES}

    @property
    def pregame_complete(self) -> bool:
        return self._first_player_seen and all(
            self._rps[role] == len(self.pregame[role]) for role in ROLES
        )

    def status(self) -> dict[str, Any]:
        return {
            "pregame_complete": self.pregame_complete,
            "first_player_role": self.first_player_role,
            "remaining_steps": self.remaining_steps(),
            "wait_for": self.wait_for,
            "ignored_decisions": self.ignored_decisions,
        }

    def _decline_optional(self, role: str, request: DecisionRequest) -> Object | None:
        if not self._optional_decline:
            return None
        kind = cast(str, request.prompt["kind"])
        decline_kind = OPTIONAL_DECLINE_KINDS.get(kind)
        if decline_kind is None:
            return None
        matches = [c for c in request.candidates if c["kind"] == decline_kind]
        if len(matches) != 1:
            return None
        candidate = matches[0]
        try:
            response = build_response(
                request,
                {"kind": "choice", "candidate_id": candidate["id"]},
                "剧本自动放弃无关可选提示",
            )
        except ContractError:
            return None
        self.ignored_decisions.append(
            {
                "role": role,
                "prompt_id": request.data["prompt_id"],
                "prompt_kind": kind,
                "candidates": [
                    {
                        "kind": item["kind"],
                        **(
                            {"card_id": cast(Object, item["card"])["card_id"]}
                            if isinstance(item.get("card"), dict)
                            and "card_id" in cast(Object, item["card"])
                            else {}
                        ),
                        **(
                            {"description_id": item["description_id"]}
                            if "description_id" in item
                            else {}
                        ),
                    }
                    for item in request.candidates
                ],
            }
        )
        return response

    def assert_visible(self, role: str, snapshot: object, expected: object) -> None:
        if role not in ROLES:
            raise ScenarioError(f"invalid role {role!r}")
        condition = _assertion(expected, "visible assertion", normalized=True)
        if not isinstance(snapshot, dict):
            raise ScenarioError("visible snapshot: expected mapping")
        actual = cast(dict[str, Any], snapshot)
        for key in ("turn", "phase", "turn_player"):
            if key in condition and actual.get(key) != condition[key]:
                raise ScenarioError(
                    f"{role} visible {key}: expected {condition[key]!r}, actual {actual.get(key)!r}"
                )
        if "life_points" in condition:
            points_raw = actual.get("life_points")
            if not isinstance(points_raw, list):
                raise ScenarioError(f"{role} visible life_points missing")
            points = cast(list[Any], points_raw)
            if len(points) != 2:
                raise ScenarioError(f"{role} visible life_points missing")
            for i, expected_point in enumerate(condition["life_points"]):
                if expected_point is not None and points[i] != expected_point:
                    raise ScenarioError(
                        f"{role} visible life_points[{i}]: "
                        f"expected {expected_point}, actual {points[i]}"
                    )
        zones_raw = actual.get("zones", [])
        if not isinstance(zones_raw, list):
            raise ScenarioError(f"{role} visible zones missing")
        zones = cast(list[Any], zones_raw)
        for wanted in condition.get("zones", []):
            zone_label = f"{role} visible zone {wanted['player']}/{wanted['name']}"
            matches = [z for z in zones if _zone_match(z, wanted)]
            if len(matches) != 1:
                raise ScenarioError(f"{zone_label}: expected one, found {len(matches)}")
            zone = cast(dict[str, Any], matches[0])
            if "count" in wanted and zone.get("count") != wanted["count"]:
                raise ScenarioError(
                    f"{zone_label} count: expected {wanted['count']}, actual {zone.get('count')}"
                )
            cards_raw = zone.get("cards", [])
            if not isinstance(cards_raw, list):
                raise ScenarioError(f"{role} visible zone cards missing")
            cards = cast(list[Any], cards_raw)
            for op in ("contains", "exact"):
                if op not in wanted:
                    continue
                desired = wanted[op]
                used: set[int] = set()
                for selector in desired:
                    quantity = selector.get("count", 1)
                    predicate = {k: v for k, v in selector.items() if k != "count"}
                    found = [
                        i
                        for i, card in enumerate(cards)
                        if i not in used and _card_match(card, predicate)
                    ]
                    if len(found) < quantity:
                        raise ScenarioError(
                            f"{zone_label}: expected {quantity} of {predicate}, found {len(found)}"
                        )
                    used.update(found[:quantity])
                if op == "exact" and len(used) != len(cards):
                    raise ScenarioError(
                        f"{zone_label}: exact assertion has {len(cards) - len(used)} extra cards"
                    )

    def _resolve(self, request: DecisionRequest, selector: dict[str, Any], context: str) -> str:
        matches = [c for c in request.candidates if _candidate_match(c, selector)]
        expected = selector.get("expected_matches", 1)
        if len(matches) != expected:
            candidates = [
                {
                    "id": c.get("id"),
                    "kind": c.get("kind"),
                    "card": c.get("card"),
                    "description": c.get("description"),
                }
                for c in request.candidates
            ]
            raise ScenarioError(
                f"{context}: selector {selector} expected {expected} matches, "
                f"found {len(matches)}; legal candidates={candidates}"
            )
        ordinal = selector.get("ordinal", 1)
        if ordinal > len(matches):
            raise ScenarioError(f"{context}: ordinal {ordinal} exceeds match count {len(matches)}")
        return cast(str, matches[ordinal - 1]["id"])

    def decide(self, role: str, request: object) -> Object:
        if role not in ROLES:
            raise ScenarioError(f"invalid role {role!r}")
        parsed = request if isinstance(request, DecisionRequest) else parse_request(request)
        kind = parsed.prompt["kind"]
        if kind == "rock_paper_scissors":
            index = self._rps[role]
            choices = self.pregame[role]
            if index >= len(choices):
                raise ScenarioError(f"{role} rock_paper_scissors: no scripted round {index + 1}")
            wanted = choices[index]
            cid = self._resolve(parsed, {"kind": wanted}, f"{role} pregame round {index + 1}")
            response = build_response(
                parsed, {"kind": "choice", "candidate_id": cid}, f"剧本赛前出拳：{wanted}"
            )
            self._rps[role] += 1
            return response
        if kind == "first_player":
            if self._first_player_seen:
                raise ScenarioError(f"{role} first_player: duplicate winner selection")
            if any(self._rps[r] != len(self.pregame[r]) for r in ROLES):
                raise ScenarioError(f"{role} first_player: scripted rock-paper-scissors incomplete")
            if role != self.rps_winner_role:
                raise ScenarioError(
                    f"{role} first_player: scripted winner is {self.rps_winner_role}"
                )
            wanted = self.pregame["winner_chooses"]
            cid = self._resolve(parsed, {"kind": wanted}, f"{role} pregame first_player")
            response = build_response(
                parsed, {"kind": "choice", "candidate_id": cid}, f"剧本选择：{wanted}"
            )
            self._first_player_seen = True
            return response
        if not self.pregame_complete:
            raise ScenarioError(f"{role} prompt {kind}: pregame selection incomplete")
        index = self._cursors[role]
        if index >= len(self.steps[role]):
            if response := self._decline_optional(role, parsed):
                return response
            raise ScenarioError(
                f"{role} prompt {kind}: no scripted step after {index} steps; "
                f"candidates={parsed.candidates}"
            )
        step = self.steps[role][index]
        expected = step["expect"]
        if kind != expected["prompt"]:
            if response := self._decline_optional(role, parsed):
                return response
            raise ScenarioError(
                f"{role} step {index + 1}: expected prompt {expected['prompt']}, "
                f"actual {kind}; candidates={parsed.candidates}"
            )
        plan = step["action"]
        action_kind = plan["kind"]
        if action_kind in ("choice", "select_step") and self._optional_decline:
            matches = [c for c in parsed.candidates if _candidate_match(c, plan["match"])]
            if not matches and (response := self._decline_optional(role, parsed)):
                return response
        try:
            self.assert_visible(
                role,
                parsed.data["observation"],
                {k: v for k, v in expected.items() if k != "prompt"},
            )
        except ScenarioError:
            if action_kind in ("choice", "select_step") and (
                response := self._decline_optional(role, parsed)
            ):
                return response
            raise
        context = f"{role} step {index + 1} prompt {kind}"
        if action_kind in ("choice", "select_step"):
            action: Object = {
                "kind": action_kind,
                "candidate_id": self._resolve(parsed, plan["match"], context),
            }
        elif action_kind == "select_cards":
            action = {
                "kind": action_kind,
                "candidate_ids": [
                    self._resolve(parsed, selector, context) for selector in plan["matches"]
                ],
            }
        elif action_kind == "select_places":
            action = {"kind": action_kind, "places": plan["places"]}
        elif action_kind == "distribute_counters":
            action = {
                "kind": action_kind,
                "allocations": [
                    {
                        "candidate_id": self._resolve(parsed, item["match"], context),
                        "count": item["count"],
                    }
                    for item in plan["allocations"]
                ],
            }
        else:
            action = {"kind": "announce_card", "card_id": plan["card_id"]}
        try:
            response = build_response(parsed, action, f"剧本 {role} 步骤 {index + 1}")
        except ContractError as exc:
            raise ScenarioError(
                f"{context}: illegal scripted action {action}; {exc}; "
                f"candidates={parsed.candidates}"
            ) from exc
        self._cursors[role] += 1
        if "wait_for" in step:
            checkpoint = step["wait_for"]
            self.wait_for.append(
                {
                    "role": role,
                    "step_index": index + 1,
                    "after_unix_ms": int(time() * 1000),
                    "timeout_ms": checkpoint["timeout_ms"],
                    "expected": checkpoint["expect"],
                }
            )
        return response
