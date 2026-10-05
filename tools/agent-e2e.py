#!/usr/bin/env python3
"""Run real LAN duels between two noninteractive agent clients."""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


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


def audit_decisions(path: Path) -> tuple[int, ...]:
    first_hand: tuple[int, ...] = ()
    submissions = 0
    outbound_actions = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("kind") == "agent_error":
                raise RuntimeError(f"{path.name}: {record.get('code')}")
            if record.get("kind") == "decision_submitted":
                submissions += 1
            if record.get("kind") == "wire_packet" and record.get("direction") == "outbound":
                frame = base64.b64decode(record["frame_base64"])
                if len(frame) >= 3 and frame[2] in (1, 3, 4):
                    outbound_actions += 1
            if record.get("kind") != "decision_request":
                continue
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
    if len(first_hand) < 5:
        raise RuntimeError(f"{path.name}: initial visible hand was not recorded")
    if submissions != outbound_actions:
        raise RuntimeError(
            f"{path.name}: {submissions} submissions but {outbound_actions} action packets"
        )
    return first_hand


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="out/build/MacOS-Debug/gframe/ygopro")
    parser.add_argument("--cards-db", default="cards.cdb")
    parser.add_argument("--deck", default="deck/test/test.ydk")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    client = (root / args.client).resolve()
    cards_db = (root / args.cards_db).resolve()
    deck = (root / args.deck).resolve()
    if args.games < 1 or args.timeout < 10 or not all(
        path.is_file() for path in (client, cards_db, deck)
    ):
        parser.error("client, cards-db, and deck must exist; games >= 1 and timeout >= 10")
    agent_port = free_port()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "agent_sdk" / "src")
    work = root / "out" / "agent-e2e-runs" / f"{int(time.time())}-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=False)
    starting_hands: dict[str, set[tuple[int, ...]]] = {"host": set(), "guest": set()}
    try:
        with (work / "agent.log").open("wb") as output:
            server = subprocess.Popen(
                [sys.executable, "-m", "agent_sdk.test_server", "--cards-db", str(cards_db),
                 "--port", str(agent_port)],
                cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                wait_for_port(agent_port, time.monotonic() + 10)
                for game in range(1, args.games + 1):
                    lan_port = free_port()
                    clients: list[subprocess.Popen[bytes]] = []
                    try:
                        for role in ("host", "guest"):
                            child_env = environment.copy()
                            child_env.update({
                                "YGOPRO_AGENT_ENABLE": "1",
                                "YGOPRO_AGENT_PORT": str(agent_port),
                                "YGOPRO_AGENT_E2E_ROLE": role,
                                "YGOPRO_AGENT_E2E_PORT": str(lan_port),
                                "YGOPRO_AGENT_E2E_DECK": str(deck),
                                "YGOPRO_AGENT_E2E_TIMEOUT_MS": str(args.timeout * 1000),
                                "YGOPRO_AGENT_E2E_RESULT_PATH": str(work / f"game-{game}-{role}.json"),
                                "YGOPRO_AGENT_LOG_PATH": str(work / f"game-{game}-{role}.jsonl"),
                            })
                            with (work / f"game-{game}-{role}.log").open("wb") as child_output:
                                clients.append(subprocess.Popen(
                                    [str(client)], cwd=root, env=child_env,
                                    stdout=child_output, stderr=subprocess.STDOUT,
                                ))
                            if role == "host":
                                wait_for_port(lan_port, time.monotonic() + 10)
                        deadline = time.monotonic() + args.timeout + 10
                        while any(child.poll() is None for child in clients):
                            if time.monotonic() >= deadline:
                                raise TimeoutError(f"game {game}: clients exceeded timeout")
                            for role, child in zip(("host", "guest"), clients, strict=True):
                                path = work / f"game-{game}-{role}.json"
                                if path.is_file():
                                    result = json.loads(path.read_text(encoding="utf-8"))
                                    if result.get("status") == "error":
                                        raise RuntimeError(f"game {game}: {role}: {result.get('error')}")
                                elif child.poll() is not None:
                                    raise RuntimeError(f"game {game}: {role} exited without result")
                            time.sleep(0.1)
                        results = []
                        for role in ("host", "guest"):
                            path = work / f"game-{game}-{role}.json"
                            if not path.is_file():
                                raise RuntimeError(f"game {game}: {role} wrote no result")
                            results.append(json.loads(path.read_text(encoding="utf-8")))
                        print(f"game {game}: {json.dumps(results, ensure_ascii=False)}", flush=True)
                        if any(
                            result.get("status") != "finished"
                            or result.get("win_seen") is not True
                            or result.get("duel_end") is not True
                            for result in results
                        ) or results[0].get("winner") != results[1].get("winner"):
                            raise RuntimeError(f"game {game}: agent duel did not finish")
                        for role in ("host", "guest"):
                            hand = audit_decisions(work / f"game-{game}-{role}.jsonl")
                            if hand in starting_hands[role]:
                                raise RuntimeError(f"game {game}: repeated {role} starting hand")
                            starting_hands[role].add(hand)
                    finally:
                        for child in clients:
                            stop(child)
            finally:
                stop(server)
    finally:
        print(f"diagnostic files retained: {work}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
