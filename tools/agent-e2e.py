#!/usr/bin/env python3
"""Run scripted LAN duels with headless or visible agent clients."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import secrets
import shlex
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

EXTRA_DECK_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000
TOKEN_TYPE = 0x4000
OBSERVABLE_RANDOM_MESSAGES = {
    33,
    36,
    81,
    130,
    131,
}  # hand shuffle, set shuffle, random select, coin, dice


def opening_from_deck(deck: Path, cards_db: Path) -> tuple[int, ...]:
    """Read the first five real main-deck cards without silently filtering YDK rows."""
    section = ""
    main: list[int] = []
    all_cards: list[int] = []
    for number, raw in enumerate(deck.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if line in ("#main", "#extra", "!side"):
            section = line
            continue
        if not line or line.startswith("#"):
            continue
        if (
            not line.isascii()
            or not line.isdigit()
            or section not in ("#main", "#extra", "!side")
        ):
            raise ValueError(f"{deck}:{number}: invalid YDK card row")
        card_id = int(line)
        all_cards.append(card_id)
        if section == "#main":
            main.append(card_id)
    if len(main) < 5:
        raise ValueError(f"{deck}: #main needs at least five cards")
    with sqlite3.connect(cards_db) as connection:
        for card_id in all_cards:
            row = connection.execute(
                "SELECT type FROM datas WHERE id = ?", (card_id,)
            ).fetchone()
            if row is None or row[0] & TOKEN_TYPE:
                raise ValueError(f"{deck}: card {card_id} is missing or a token")
        for card_id in main[:5]:
            row = connection.execute(
                "SELECT type FROM datas WHERE id = ?", (card_id,)
            ).fetchone()
            if row is None or row[0] & EXTRA_DECK_TYPES:
                raise ValueError(
                    f"{deck}: opening card {card_id} is not a main-deck card"
                )
    return tuple(main[:5])


class SnapshotTail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.pending = b""
        self.snapshots: list[dict[str, Any]] = []
        self.opening_hand: tuple[int, ...] | None = None
        self.random_messages: list[int] = []

    def poll(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("rb") as source:
            source.seek(self.offset)
            chunk = source.read()
            self.offset = source.tell()
        if not chunk:
            return
        parts = (self.pending + chunk).split(b"\n")
        self.pending = parts.pop()
        for part in parts:
            record = json.loads(part)
            if record.get("kind") == "diagnostic_log_truncated":
                raise RuntimeError(
                    f"{self.path.name}: diagnostic log exceeded size limit"
                )
            if record.get("kind") != "visible_snapshot":
                continue
            self.snapshots.append(record)
            if record["message_type"] in OBSERVABLE_RANDOM_MESSAGES:
                self.random_messages.append(record["message_type"])
            if self.opening_hand is not None:
                continue
            for zone in record["observation"]["zones"]:
                if (
                    zone["player"] == 0
                    and zone["name"] == "hand"
                    and zone["count"] == 5
                ):
                    cards = zone["cards"]
                    if len(cards) != 5 or any("card_id" not in card for card in cards):
                        raise RuntimeError(
                            f"{self.path.name}: opening hand contains unknown cards"
                        )
                    self.opening_hand = tuple(card["card_id"] for card in cards)


def check_opening(
    role: str, actual: tuple[int, ...] | None, expected: tuple[int, ...]
) -> None:
    if actual is not None and Counter(actual) != Counter(expected):
        raise RuntimeError(
            f"{role}: opening hand {actual} differs from YDK first five {expected}"
        )


def matching_snapshot_time(
    scenario: Any,
    role: str,
    expected: dict[str, Any],
    snapshots: list[dict[str, Any]],
    after_unix_ms: int,
) -> int | None:
    for record in snapshots:
        if record["timestamp_unix_ms"] < after_unix_ms:
            continue
        try:
            scenario.assert_visible(role, record["observation"], expected)
        except ValueError:
            continue
        return int(record["timestamp_unix_ms"])
    return None


def matching_snapshot(
    scenario: Any,
    role: str,
    expected: dict[str, Any],
    snapshots: list[dict[str, Any]],
    after_unix_ms: int,
) -> bool:
    return (
        matching_snapshot_time(scenario, role, expected, snapshots, after_unix_ms)
        is not None
    )


def post_random_snapshot_seen(
    scenario: Any,
    role: str,
    snapshots: list[dict[str, Any]],
    target_message: int,
    last_action_unix_ms: int,
    requirements: tuple[dict[str, Any], ...],
) -> bool:
    """Require every post-effect assertion on the same snapshot after the result."""
    positions = [
        index
        for index, record in enumerate(snapshots)
        if record.get("message_type") == target_message
    ]
    if len(positions) != 1:
        raise RuntimeError(
            f"{role}: expected exactly one target random message, found {len(positions)}"
        )
    for record in snapshots[positions[0] + 1 :]:
        if record["timestamp_unix_ms"] < last_action_unix_ms:
            continue
        try:
            for expected in requirements:
                scenario.assert_visible(role, record["observation"], expected)
        except ValueError:
            continue
        return True
    return False


def checkpoint_failure(
    scenario: Any, status: dict[str, Any], tails: dict[str, SnapshotTail]
) -> str:
    differences = []
    for role, expected in scenario.goal["expect"].items():
        if matching_snapshot(
            scenario,
            role,
            expected,
            tails[role].snapshots,
            status["last_action_unix_ms"],
        ):
            continue
        if not tails[role].snapshots:
            differences.append(f"{role}: no visible snapshot")
            continue
        try:
            scenario.assert_visible(
                role, tails[role].snapshots[-1]["observation"], expected
            )
        except ValueError as exc:
            differences.append(str(exc))
        else:
            differences.append(f"{role}: no snapshot after final action")
    return "; ".join(differences)


def assert_recorded_events(
    scenario: Any, work: Path, *, protocol: str = "v2"
) -> dict[str, list[dict[str, Any]]]:
    """Check each perspective's durably accepted event history."""
    if (
        not any(scenario.event_assertions.values())
        and not any(scenario.event_count_assertions.values())
        and scenario.random_target is None
    ):
        return {}
    if protocol == "v3":
        accepted = {
            role: load_v3_duel(work, role)["events"] for role in ("host", "guest")
        }
        for role, expected in scenario.event_assertions.items():
            if expected or scenario.event_count_assertions[role]:
                scenario.assert_events(role, accepted[role])
        return accepted
    from agent_sdk.state_journal import StateJournal

    journal_root = work / "state"
    journal = StateJournal(journal_root)
    accepted: dict[str, list[dict[str, Any]]] = {}
    for path in journal_root.glob("*.json"):
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        state = wrapper["state"]
        session, duel = state["session_id"], state["duel_id"]
        version = journal.get_status(session, duel)["state_version"]
        if not version:
            continue
        role = journal.get_state(session, duel, 1).get("test_role")
        if role not in ("host", "guest"):
            continue
        if role in accepted:
            raise RuntimeError(
                f"{role}: multiple accepted event journals in one scenario"
            )
        events: list[dict[str, Any]] = []
        after = 0
        while batch := journal.get_events(
            session, duel, after_event_id=after, limit=1000
        ):
            events.extend(batch)
            after = batch[-1]["event_id"]
        accepted[role] = events
    for role, expected in scenario.event_assertions.items():
        if not expected and not scenario.event_count_assertions[role]:
            continue
        if role not in accepted:
            raise RuntimeError(f"{role}: accepted event journal missing")
        scenario.assert_events(role, accepted[role])
    return accepted


def load_v3_duel(work: Path, role: str) -> dict[str, Any]:
    """Read only this run's v3 child-service database for one perspective."""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "agent_server" / "src"))
    from agent_server.storage import StateDatabase

    database = work / "agent-data" / f"e2e-{role}-local" / "state.sqlite3"
    if not database.is_file():
        raise RuntimeError(f"{role}: v3 state database missing: {database}")
    with StateDatabase(database, read_only=True) as store:
        duels = store.list_duels()
        if len(duels) != 1:
            raise RuntimeError(f"{role}: expected one v3 duel, found {len(duels)}")
        session = duels[0]["session_id"]
        duel = duels[0]["duel_id"]
        status = store.get_status(session, duel)
        if status["state_version"] < 1:
            raise RuntimeError(f"{role}: v3 duel has no accepted decision snapshot")
        first = store.get_state(session, duel, 1)
        if first.get("test_role") != role:
            raise RuntimeError(f"{role}: v3 database perspective differs")
        events: list[dict[str, Any]] = []
        after_event_id = 0
        while batch := store.get_events(
            session, duel, after_event_id=after_event_id, limit=1000
        ):
            events.extend(batch)
            after_event_id = batch[-1]["event_id"]
        records: list[dict[str, Any]] = []
        after_record_id = 0
        while batch := store.get_records(
            session, duel, after_id=after_record_id, limit=1000
        ):
            records.extend(batch)
            after_record_id = batch[-1]["id"]
    return {"events": events, "records": records, "status": status}


def audit_v3_duel(work: Path, role: str, *, terminal: bool) -> None:
    """Require v3-only binding and receipts on the scripted transport path."""
    accepted = load_v3_duel(work, role)
    records = accepted["records"]
    kinds = [record["kind"] for record in records]
    if kinds.count("deck_manifest") != 1:
        raise RuntimeError(
            f"{role}: v3 deck manifest was not durably bound exactly once"
        )
    actions = [record for record in records if record["kind"] == "agent_action"]
    receipts = [record for record in records if record["kind"] == "action_receipt"]
    if not actions or not receipts:
        raise RuntimeError(f"{role}: v3 action issuance or client receipt missing")
    issued = {record["record_id"] for record in actions}
    if any(record["record_id"] not in issued for record in receipts):
        raise RuntimeError(f"{role}: v3 receipt has no matching issued action")
    if any(record["payload"].get("status") != "submitted" for record in receipts):
        raise RuntimeError(f"{role}: v3 client rejected a scripted action")
    if terminal and not any(
        event["kind"] == "duel_ended" for event in accepted["events"]
    ):
        raise RuntimeError(f"{role}: v3 terminal sync was not durably accepted")


def run_scripted_duel(
    scenario: Any,
    work: Path,
    clients: list[subprocess.Popen[bytes]],
    expected_opening: dict[str, tuple[int, ...]],
    timeout: int,
    *,
    protocol: str = "v2",
    gui: bool = False,
    step_delay: float = 0,
) -> dict[str, Any]:
    roles = ("host", "guest")
    tails = {role: SnapshotTail(work / f"game-1-{role}.jsonl") for role in roles}
    status_path = work / "scenario-status.json"
    surrender = scenario.goal.get("surrender")
    surrender_role = surrender["role"] if surrender else None
    surrender_path = work / f"surrender-{surrender_role}.request"
    checkpoint_path = work / "checkpoint-reached.request"
    deadline = time.monotonic() + timeout + 10
    while time.monotonic() < deadline:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status["status"] == "error":
            raise RuntimeError(f"scenario mismatch: {status['error']}")
        for role, child in zip(roles, clients, strict=True):
            tails[role].poll()
            check_opening(role, tails[role].opening_hand, expected_opening[role])
            unapproved_random = [
                message
                for message in tails[role].random_messages
                if message not in scenario.allowed_random_messages
            ]
            if unapproved_random:
                raise RuntimeError(
                    f"{role}: observable uncontrolled random message "
                    f"{unapproved_random[0]} in fixed-deck scenario"
                )
            result_path = work / f"game-1-{role}.json"
            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if result["status"] == "error":
                    if (
                        scenario.goal["kind"] == "checkpoint"
                        and status["pregame_complete"]
                        and not any(status["remaining_steps"].values())
                    ):
                        detail = checkpoint_failure(scenario, status, tails)
                        raise RuntimeError(
                            f"checkpoint not reached: {detail}; "
                            f"{role} client error: {result['error']}"
                        )
                    raise RuntimeError(f"{role}: {result['error']}")
            elif child.poll() is not None:
                raise RuntimeError(f"{role}: client exited without a result")
        for wait in status["wait_for"]:
            role = wait["role"]
            if (
                not matching_snapshot(
                    scenario,
                    role,
                    wait["expected"],
                    tails[role].snapshots,
                    wait["after_unix_ms"],
                )
                and time.time_ns() // 1_000_000
                > wait["after_unix_ms"] + wait["timeout_ms"]
            ):
                raise RuntimeError(
                    f"{role} step {wait['step_index']}: wait_for timed out; "
                    f"expected={wait['expected']}; "
                    f"last={tails[role].snapshots[-1] if tails[role].snapshots else None}"
                )
        hands_ready = all(tails[role].opening_hand is not None for role in roles)
        steps_done = status["pregame_complete"] and not any(
            status["remaining_steps"].values()
        )
        waits_done = all(
            matching_snapshot(
                scenario,
                wait["role"],
                wait["expected"],
                tails[wait["role"]].snapshots,
                wait["after_unix_ms"],
            )
            for wait in status["wait_for"]
        )
        surrender_snapshots = (
            [
                matching_snapshot_time(
                    scenario,
                    role,
                    surrender["expect"][role],
                    tails[role].snapshots,
                    status["last_action_unix_ms"],
                )
                for role in roles
            ]
            if surrender and hands_ready and steps_done and waits_done
            else []
        )
        if (
            surrender
            and not surrender_path.exists()
            and len(surrender_snapshots) == 2
            and all(timestamp is not None for timestamp in surrender_snapshots)
            and time.time_ns() // 1_000_000
            >= max(
                timestamp for timestamp in surrender_snapshots if timestamp is not None
            )
            + int(step_delay * 1000)
        ):
            surrender_path.write_text("surrender\n", encoding="ascii")
        if (
            scenario.goal["kind"] == "checkpoint"
            and hands_ready
            and steps_done
            and waits_done
            and (
                scenario.random_target is None
                or all(
                    any(
                        record.get("message_type")
                        == scenario.random_target["message_type"]
                        for record in tails[role].snapshots
                    )
                    for role in roles
                )
            )
            and all(
                matching_snapshot(
                    scenario,
                    role,
                    scenario.goal["expect"][role],
                    tails[role].snapshots,
                    status["last_action_unix_ms"],
                )
                for role in roles
            )
        ):
            accepted = assert_recorded_events(scenario, work, protocol=protocol)
            random_case_key = None
            if scenario.random_target is not None:
                random_case_key, random_case = scenario.match_random_case(accepted)
                target_message = scenario.random_target["message_type"]
                post_effect_ready = True
                for role in roles:
                    requirements = (
                        scenario.goal["expect"][role],
                        scenario.random_target["expect"][role],
                        random_case["expect"][role],
                    )
                    if not post_random_snapshot_seen(
                        scenario,
                        role,
                        tails[role].snapshots,
                        target_message,
                        status["last_action_unix_ms"],
                        requirements,
                    ):
                        post_effect_ready = False
                        break
                if not post_effect_ready:
                    time.sleep(0.05)
                    continue
            for role in roles:
                audit_decisions(tails[role].path, require_hand=False)
                if protocol == "v3":
                    audit_v3_duel(work, role, terminal=False)
            if gui:
                checkpoint_path.write_text("reached\n", encoding="ascii")
                checkpoint_deadline = time.monotonic() + 5
                while time.monotonic() < checkpoint_deadline:
                    if all((work / f"game-1-{role}.json").is_file() for role in roles):
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("GUI clients did not acknowledge checkpoint")
            return {
                "status": "checkpoint_passed",
                "opening_hands": {role: tails[role].opening_hand for role in roles},
                "decisions": status["decisions"],
                **(
                    {"random_case": random_case_key}
                    if random_case_key is not None
                    else {}
                ),
            }
        if all((work / f"game-1-{role}.json").is_file() for role in roles) and (
            gui or all(child.poll() is not None for child in clients)
        ):
            if scenario.goal["kind"] != "duel_end":
                raise RuntimeError("clients ended before checkpoint was reached")
            if not hands_ready or not steps_done or not waits_done:
                raise RuntimeError(f"duel ended before scenario completed: {status}")
            results = [
                json.loads((work / f"game-1-{role}.json").read_text(encoding="utf-8"))
                for role in roles
            ]
            if (
                any(
                    result["status"] != "finished"
                    or not result["win_seen"]
                    or not result["duel_end"]
                    for result in results
                )
                or results[0]["winner"] != results[1]["winner"]
            ):
                raise RuntimeError(f"authoritative duel result differs: {results}")
            raw_winner = results[0]["winner"]
            first = status["first_player_role"]
            winner = (
                "draw"
                if raw_winner == 2
                else (
                    first
                    if raw_winner == 0
                    else ("guest" if first == "host" else "host")
                )
            )
            if scenario.goal["winner"] not in ("any", winner):
                raise RuntimeError(
                    f"winner {winner} differs from expected {scenario.goal['winner']}"
                )
            if "expect" in scenario.goal:
                for role in roles:
                    terminal = [
                        record
                        for record in tails[role].snapshots
                        if record["message_type"] == 5
                    ]
                    if not terminal:
                        raise RuntimeError(f"{role}: terminal MSG_WIN snapshot missing")
                    try:
                        scenario.assert_visible(
                            role,
                            terminal[-1]["observation"],
                            scenario.goal["expect"][role],
                        )
                    except ValueError as exc:
                        raise RuntimeError(
                            f"{role}: terminal visible state differs from goal.expect: {exc}"
                        ) from exc
            if surrender and (
                not surrender_path.exists()
                or not results[roles.index(surrender_role)].get("surrender_sent")
            ):
                raise RuntimeError(f"scripted {surrender_role} surrender was not sent")
            assert_recorded_events(scenario, work, protocol=protocol)
            for role in roles:
                audit_decisions(tails[role].path, require_hand=False)
                if protocol == "v3":
                    audit_v3_duel(work, role, terminal=True)
            return {"status": "duel_finished", "winner": winner, "results": results}
        time.sleep(0.05)
    raise TimeoutError(
        f"scripted duel exceeded {timeout}s; status="
        f"{status_path.read_text(encoding='utf-8')}; "
        f"last_snapshots={{{', '.join(f'{role}: {tails[role].snapshots[-1] if tails[role].snapshots else None}' for role in roles)}}}"
    )


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_port(port: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"port {port} did not open")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def audit_decisions(path: Path, *, require_hand: bool = True) -> tuple[int, ...]:
    first_hand: tuple[int, ...] = ()
    submissions = 0
    automatic_passes = 0
    outbound_actions = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("kind") == "diagnostic_log_truncated":
                raise RuntimeError(f"{path.name}: diagnostic log exceeded size limit")
            if record.get("kind") == "agent_error":
                raise RuntimeError(f"{path.name}: {record.get('code')}")
            if record.get("kind") == "decision_submitted":
                submissions += 1
            if record.get("kind") == "automatic_pass":
                automatic_passes += 1
            if (
                record.get("kind") == "wire_packet"
                and record.get("direction") == "outbound"
            ):
                frame = base64.b64decode(record["frame_base64"])
                if len(frame) >= 3 and frame[2] in (1, 3, 4):
                    outbound_actions += 1
            if record.get("kind") != "decision_request":
                continue
            prompt = record["message"]["prompt"]
            if prompt["kind"] == "chain" and all(
                candidate["kind"] == "pass" for candidate in prompt["candidates"]
            ):
                raise RuntimeError(f"{path.name}: empty chain window reached Agent")
            for zone in record["message"]["observation"]["zones"]:
                if zone["name"] == "deck" and zone["cards"]:
                    raise RuntimeError(f"{path.name}: deck contents leaked")
                if zone["player"] == 1 and zone["name"] == "hand" and zone["cards"]:
                    raise RuntimeError(f"{path.name}: opponent hand leaked")
                for card in zone["cards"]:
                    if card.get("known") is False and "card_id" in card:
                        raise RuntimeError(f"{path.name}: hidden card identity leaked")
                if (
                    not first_hand
                    and zone["player"] == 0
                    and zone["name"] == "hand"
                    and zone["count"] >= 5
                ):
                    first_hand = tuple(card["card_id"] for card in zone["cards"])
    if require_hand and len(first_hand) < 5:
        raise RuntimeError(f"{path.name}: initial visible hand was not recorded")
    if submissions + automatic_passes != outbound_actions:
        raise RuntimeError(
            f"{path.name}: {submissions} submissions and {automatic_passes} "
            f"automatic passes but {outbound_actions} action packets"
        )
    return first_hand


def write_scenario_report(
    work: Path,
    scenario: Any,
    decks: dict[str, Path],
    expected_opening: dict[str, tuple[int, ...]],
    outcome: dict[str, Any] | None,
    failure: BaseException | None,
    *,
    protocol: str,
) -> None:
    """Keep a compact, visible-only summary even when the duel aborts early."""
    status_path = work / "scenario-status.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic_dir": str(work),
        "agent_http_protocol": protocol,
        "scenario": str(scenario.source),
        "status": "failed" if failure else "passed",
        "error": str(failure) if failure else None,
        "result": outcome,
        "goal": scenario.goal,
        "scenario_status": (
            json.loads(status_path.read_text(encoding="utf-8"))
            if status_path.is_file()
            else None
        ),
        "roles": {},
    }
    for role in ("host", "guest"):
        last_snapshot = None
        opening_hand = None
        last_prompt = None
        log_path = work / f"game-1-{role}.jsonl"
        if log_path.is_file():
            with log_path.open(encoding="utf-8") as source:
                for line in source:
                    record = json.loads(line)
                    if record.get("kind") == "visible_snapshot":
                        last_snapshot = record
                        if opening_hand is None:
                            for zone in record["observation"]["zones"]:
                                if (
                                    zone["player"] == 0
                                    and zone["name"] == "hand"
                                    and zone["count"] == 5
                                ):
                                    opening_hand = [
                                        card.get("card_id") for card in zone["cards"]
                                    ]
                    elif record.get("kind") == "decision_request":
                        last_prompt = record["message"]
        result_path = work / f"game-1-{role}.json"
        report["roles"][role] = {
            "deck": str(decks[role]),
            "expected_opening": expected_opening[role],
            "actual_opening": opening_hand,
            "last_visible_snapshot": last_snapshot,
            "last_decision_request": last_prompt,
            "client_result": (
                json.loads(result_path.read_text(encoding="utf-8"))
                if result_path.is_file()
                else None
            ),
            **(
                {
                    "agent_state_db": str(
                        work / "agent-data" / f"e2e-{role}-local" / "state.sqlite3"
                    )
                }
                if protocol == "v3"
                else {}
            ),
        }
    (work / "scenario-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_scenario_batch(
    args: argparse.Namespace, root: Path, parser: argparse.ArgumentParser
) -> int:
    """Run each reviewed YAML scenario in an isolated child invocation."""
    if args.gui or args.step_delay is not None or args.record_output:
        parser.error("--scenario-dir supports headless replay only")
    if (
        args.games is not None
        or args.host_deck
        or args.guest_deck
        or args.report_output
        or args.deck != "deck/test/test.ydk"
    ):
        parser.error("--scenario-dir cannot override individual scenario runs")
    if args.agent_v3_offline and args.protocol == "v2":
        parser.error("--agent-v3-offline conflicts with --protocol v2")
    if args.timeout < 10:
        parser.error("--timeout must be at least 10 seconds")
    if not (root / args.client).is_file() or not (root / args.cards_db).is_file():
        parser.error("client and cards-db must exist")
    directory = (root / args.scenario_dir).resolve()
    if not directory.is_dir():
        parser.error(f"scenario directory does not exist: {directory}")
    scenarios = sorted(
        directory.rglob("scenario.yaml"),
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    if not scenarios:
        parser.error(f"no scenario.yaml files under {directory}")
    sys.path.insert(0, str(root / "agent_sdk" / "src"))
    from agent_sdk.scenario import Scenario

    work = root / "out" / "agent-e2e-runs" / f"batch-{int(time.time())}-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []

    def write_summary() -> dict[str, Any]:
        counts = {
            name: sum(entry["status"] == name for entry in entries)
            for name in ("passed", "failed", "unsupported")
        }
        summary = {
            "schema_version": 1,
            "status": (
                "running"
                if len(entries) < len(scenarios)
                else "passed"
                if counts["passed"] == len(scenarios)
                else "failed"
            ),
            "agent_http_protocol": args.protocol,
            "scenario_dir": str(directory),
            "total": len(scenarios),
            "counts": counts,
            "scenarios": entries,
        }
        temporary = work / "batch-report.json.tmp"
        temporary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, work / "batch-report.json")
        return summary

    write_summary()
    for index, path in enumerate(scenarios, 1):
        relative = path.relative_to(directory).as_posix()
        print(f"[{index}/{len(scenarios)}] {relative}", flush=True)
        report_path = work / f"scenario-{index:03d}.json"
        log_path = work / f"scenario-{index:03d}.log"
        entry: dict[str, Any] = {
            "scenario": relative,
            "status": "failed",
            "report": str(report_path),
            "log": str(log_path),
            "diagnostic_dir": None,
            "exit_code": None,
            "error": None,
        }
        try:
            missing = [
                name
                for name in ("host.ydk", "guest.ydk", "goal.md", "README.md")
                if not (path.parent / name).is_file()
            ]
            if missing:
                raise ValueError(
                    f"incomplete scenario package: missing {', '.join(missing)}"
                )
            scenario = Scenario.load(path)
            command = [
                sys.executable,
                str(
                    root
                    / "tools"
                    / (
                        "sample-random-scenario.py"
                        if scenario.random_target is not None
                        else "agent-e2e.py"
                    )
                ),
                "--scenario",
                str(path),
                "--protocol",
                args.protocol,
                "--client",
                str(args.client),
                "--cards-db",
                str(args.cards_db),
                "--timeout",
                str(args.timeout),
                "--report-output",
                str(report_path),
            ]
            with log_path.open("wb") as output:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            entry["exit_code"] = completed.returncode
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                entry["diagnostic_dir"] = report.get("diagnostic_dir")
                entry["error"] = report.get("error")
                expected_status = (
                    ("covered", "single_passed")
                    if scenario.random_target is not None
                    else ("passed",)
                )
                if (
                    completed.returncode == 0
                    and report.get("status") in expected_status
                ):
                    entry["status"] = "passed"
            if entry["status"] != "passed" and not entry["error"]:
                entry["error"] = "child failed or did not produce a passing report"
        except (OSError, ValueError, KeyError) as exc:
            entry["error"] = str(exc)
            if not log_path.exists():
                log_path.write_text(entry["error"] + "\n", encoding="utf-8")
        entries.append(entry)
        write_summary()
        print(f"  {entry['status']}: {entry['error'] or report_path}", flush=True)
    summary = write_summary()
    print(f"batch report: {work / 'batch-report.json'}", flush=True)
    return 0 if summary["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="out/build/MacOS-Debug/gframe/ygopro")
    parser.add_argument("--cards-db", default="cards.cdb")
    parser.add_argument("--deck", default="deck/test/test.ydk")
    parser.add_argument("--host-deck")
    parser.add_argument("--guest-deck")
    scenario_group = parser.add_mutually_exclusive_group()
    scenario_group.add_argument("--scenario", help="YAML scripted fixed-deck duel")
    scenario_group.add_argument(
        "--scenario-dir",
        nargs="?",
        const="tests/scenarios",
        help="run every deterministic scenario.yaml below DIR (default: tests/scenarios)",
    )
    parser.add_argument("--report-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--protocol",
        choices=("v2", "v3"),
        default="v3",
        help="Agent HTTP protocol for the deterministic test service (default: v3)",
    )
    parser.add_argument(
        "--agent-v3-offline",
        action="store_true",
        help="legacy alias for the default --protocol v3",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="show both duel clients and retain their windows",
    )
    parser.add_argument(
        "--step-delay",
        type=float,
        default=None,
        help="seconds to view each scripted action after animation (GUI default: 1)",
    )
    parser.add_argument("--games", type=int)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--record-output", help="capture both clients while running one scripted duel"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.scenario_dir is not None:
        return run_scenario_batch(args, root, parser)
    client = (root / args.client).resolve()
    cards_db = (root / args.cards_db).resolve()
    scenario_path = (root / args.scenario).resolve() if args.scenario else None
    scenario = None
    if scenario_path:
        sys.path.insert(0, str(root / "agent_sdk" / "src"))
        try:
            from agent_sdk.scenario import Scenario

            scenario = Scenario.load(scenario_path)
        except (ImportError, ValueError, OSError) as exc:
            parser.error(f"cannot load scenario: {exc}")
    deck_default = (root / args.deck).resolve()
    decks = {
        role: (root / override).resolve()
        if override
        else (
            (scenario.source.parent / scenario.decks[role]).resolve()
            if scenario
            else deck_default
        )
        for role, override in (("host", args.host_deck), ("guest", args.guest_deck))
    }
    games = args.games if args.games is not None else (1 if scenario else 3)
    if (
        games < 1
        or args.timeout < 10
        or not all(path.is_file() for path in (client, cards_db, *decks.values()))
    ):
        parser.error(
            "client, cards-db, and both decks must exist; games >= 1 and timeout >= 10"
        )
    if scenario and games != 1:
        parser.error("scripted scenarios run exactly one duel")
    if args.record_output and (not scenario or games != 1):
        parser.error("--record-output requires one scripted duel")
    if args.gui and not scenario:
        parser.error("--gui requires --scenario")
    if args.agent_v3_offline and args.protocol == "v2":
        parser.error("--agent-v3-offline conflicts with --protocol v2")
    if args.step_delay is not None and not args.gui:
        parser.error("--step-delay requires --gui")
    step_delay = (
        (1.0 if args.step_delay is None else args.step_delay) if args.gui else 0.0
    )
    if not math.isfinite(step_delay) or not 0 <= step_delay <= 10:
        parser.error("--step-delay must be between 0 and 10 seconds")
    scripted_actions = (
        sum(
            len(scenario.steps[role]) + len(scenario.pregame[role])
            for role in ("host", "guest")
        )
        + 1
        + int("surrender" in scenario.goal)
        if scenario
        else 0
    )
    effective_timeout = args.timeout + math.ceil(scripted_actions * step_delay)
    expected_opening = (
        {role: opening_from_deck(deck, cards_db) for role, deck in decks.items()}
        if scenario
        else {}
    )
    agent_port = free_port()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "agent_sdk" / "src")
    work = root / "out" / "agent-e2e-runs" / f"{int(time.time())}-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=False)
    use_v3 = args.protocol == "v3"
    if use_v3 and scenario:
        environment["YGOPRO_AGENT_E2E_SCENARIO_TOKEN"] = secrets.token_urlsafe(32)
    offline_profiles: dict[str, str] = {}
    if use_v3:
        template = (root / ".agents/config.example.toml").read_text(encoding="utf-8")
        launcher = work / "agent-server-offline"
        oracle_arg = (
            " --scenario-oracle "
            + shlex.quote(f"http://127.0.0.1:{agent_port}/v3/scenario-action")
            if scenario
            else ""
        )
        launcher.write_text(
            "#!/bin/sh\nexec "
            + shlex.quote(str(root / "agent_server/.venv/bin/python"))
            + " -m agent_server --offline"
            + oracle_arg
            + ' "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        environment["YGOPRO_AGENT_PROTOCOL"] = "v3"
        environment["YGOPRO_AGENT_SERVER_EXECUTABLE"] = str(launcher)
        for role in ("host", "guest"):
            profile = f"e2e-{role}-local"
            path = root / ".agents" / f"{profile}.toml"
            if path.exists():
                raise ValueError(f"temporary Agent profile already exists: {path}")
        for role in ("host", "guest"):
            profile = f"e2e-{role}-local"
            path = root / ".agents" / f"{profile}.toml"
            path.write_text(
                template.replace("port = 8910", f"port = {free_port()}", 1).replace(
                    'directory = ".agents/data"',
                    f'directory = "{(work / "agent-data").relative_to(root)}"',
                    1,
                ),
                encoding="utf-8",
            )
            offline_profiles[role] = profile
    record_dir = (root / args.record_output).resolve() if args.record_output else None
    record_id = uuid.uuid4().hex if record_dir else None
    if record_dir:
        record_dir.mkdir(parents=True, exist_ok=False)
    starting_hands: dict[str, set[tuple[int, ...]]] = {"host": set(), "guest": set()}
    outcome: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        with (work / "agent.log").open("wb") as output:
            server: subprocess.Popen[bytes] | None = None
            if scenario or not use_v3:
                command = (
                    [
                        sys.executable,
                        "-m",
                        "agent_sdk.scenario_server",
                        "--scenario",
                        str(scenario_path),
                        "--status-path",
                        str(work / "scenario-status.json"),
                        "--cards-db",
                        str(cards_db),
                        "--port",
                        str(agent_port),
                        "--step-delay",
                        str(step_delay),
                        *(
                            ("--token-env", "YGOPRO_AGENT_E2E_SCENARIO_TOKEN")
                            if use_v3
                            else ()
                        ),
                    ]
                    if scenario
                    else [
                        sys.executable,
                        "-m",
                        "agent_sdk.test_server",
                        "--cards-db",
                        str(cards_db),
                        "--port",
                        str(agent_port),
                    ]
                )
                server = subprocess.Popen(
                    command,
                    cwd=root,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            try:
                if server is not None:
                    wait_for_port(agent_port, time.monotonic() + 10)
                for game in range(1, games + 1):
                    lan_port = free_port()
                    clients: list[subprocess.Popen[bytes]] = []
                    try:
                        for role in ("host", "guest"):
                            child_env = environment.copy()
                            if use_v3:
                                child_env["YGOPRO_AGENT_CONFIG"] = offline_profiles[
                                    role
                                ]
                            child_env.update(
                                {
                                    "YGOPRO_AGENT_ENABLE": "1",
                                    "YGOPRO_AGENT_PORT": str(agent_port),
                                    "YGOPRO_AGENT_E2E_ROLE": role,
                                    "YGOPRO_AGENT_E2E_PORT": str(lan_port),
                                    "YGOPRO_AGENT_E2E_DECK": str(decks[role]),
                                    "YGOPRO_AGENT_E2E_TIMEOUT_MS": str(
                                        effective_timeout * 1000
                                    ),
                                    "YGOPRO_AGENT_E2E_RESULT_PATH": str(
                                        work / f"game-{game}-{role}.json"
                                    ),
                                    "YGOPRO_AGENT_LOG_PATH": str(
                                        work / f"game-{game}-{role}.jsonl"
                                    ),
                                }
                            )
                            if scenario:
                                child_env["YGOPRO_AGENT_E2E_FIXED_DECK"] = "1"
                                if scenario.random_target is not None:
                                    child_env["YGOPRO_AGENT_E2E_SYNC_MESSAGE_TYPE"] = (
                                        str(scenario.random_target["message_type"])
                                    )
                                if record_dir:
                                    child_env["YGOPRO_DUEL_RECORD_ID"] = record_id or ""
                                    child_env["YGOPRO_DUEL_RECORD_ROLE"] = role
                                    child_env["YGOPRO_DUEL_RECORD_PATH"] = str(
                                        record_dir / f"{role}.jsonl"
                                    )
                                if args.gui:
                                    child_env["YGOPRO_AGENT_E2E_GUI"] = "1"
                                    child_env["YGOPRO_AGENT_E2E_CHECKPOINT_PATH"] = str(
                                        work / "checkpoint-reached.request"
                                    )
                                    child_env["YGOPRO_AGENT_TIMEOUT_MS"] = str(
                                        max(
                                            20000,
                                            math.ceil((2 * step_delay + 10) * 1000),
                                        )
                                    )
                                if (
                                    "surrender" in scenario.goal
                                    and role == scenario.goal["surrender"]["role"]
                                ):
                                    child_env["YGOPRO_AGENT_E2E_SURRENDER_PATH"] = str(
                                        work / f"surrender-{role}.request"
                                    )
                            with (work / f"game-{game}-{role}.log").open(
                                "wb"
                            ) as child_output:
                                clients.append(
                                    subprocess.Popen(
                                        [str(client)],
                                        cwd=root,
                                        env=child_env,
                                        stdout=child_output,
                                        stderr=subprocess.STDOUT,
                                        start_new_session=args.gui
                                        and os.name == "posix",
                                    )
                                )
                            if role == "host":
                                wait_for_port(lan_port, time.monotonic() + 10)
                        if scenario:
                            outcome = run_scripted_duel(
                                scenario,
                                work,
                                clients,
                                expected_opening,
                                effective_timeout,
                                protocol=args.protocol,
                                gui=args.gui,
                                step_delay=step_delay,
                            )
                            print(
                                f"scenario: {json.dumps(outcome, ensure_ascii=False)}",
                                flush=True,
                            )
                            continue
                        deadline = time.monotonic() + args.timeout + 10
                        while any(child.poll() is None for child in clients):
                            if time.monotonic() >= deadline:
                                raise TimeoutError(
                                    f"game {game}: clients exceeded timeout"
                                )
                            for role, child in zip(
                                ("host", "guest"), clients, strict=True
                            ):
                                path = work / f"game-{game}-{role}.json"
                                if path.is_file():
                                    result = json.loads(
                                        path.read_text(encoding="utf-8")
                                    )
                                    if result.get("status") == "error":
                                        raise RuntimeError(
                                            f"game {game}: {role}: {result.get('error')}"
                                        )
                                elif child.poll() is not None:
                                    raise RuntimeError(
                                        f"game {game}: {role} exited without result"
                                    )
                            time.sleep(0.1)
                        results = []
                        for role in ("host", "guest"):
                            path = work / f"game-{game}-{role}.json"
                            if not path.is_file():
                                raise RuntimeError(
                                    f"game {game}: {role} wrote no result"
                                )
                            results.append(json.loads(path.read_text(encoding="utf-8")))
                        print(
                            f"game {game}: {json.dumps(results, ensure_ascii=False)}",
                            flush=True,
                        )
                        if any(
                            result.get("status") != "finished"
                            or result.get("win_seen") is not True
                            or result.get("duel_end") is not True
                            for result in results
                        ) or results[0].get("winner") != results[1].get("winner"):
                            raise RuntimeError(
                                f"game {game}: agent duel did not finish"
                            )
                        for role in ("host", "guest"):
                            hand = audit_decisions(work / f"game-{game}-{role}.jsonl")
                            if hand in starting_hands[role]:
                                raise RuntimeError(
                                    f"game {game}: repeated {role} starting hand"
                                )
                            starting_hands[role].add(hand)
                    finally:
                        if not args.gui:
                            for child in clients:
                                stop(child)
            finally:
                if server is not None:
                    stop(server)
    except Exception as exc:
        failure = exc
        raise
    finally:
        for profile in offline_profiles.values():
            (root / ".agents" / f"{profile}.toml").unlink(missing_ok=True)
        if scenario:
            write_scenario_report(
                work,
                scenario,
                decks,
                expected_opening,
                outcome,
                failure,
                protocol=args.protocol,
            )
            if args.report_output:
                args.report_output.parent.mkdir(parents=True, exist_ok=True)
                args.report_output.write_bytes(
                    (work / "scenario-report.json").read_bytes()
                )
            print(f"scenario report: {work / 'scenario-report.json'}", flush=True)
        print(f"diagnostic files retained: {work}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
