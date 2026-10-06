#!/usr/bin/env python3
"""Re-pair a legacy capture's responses with the inbound prompt that caused them."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path
from typing import Any

RESPONSE_TYPES = {1, 3, 4}
PRE_DUEL = {
    "rock_paper_scissors": (3, "select_hand"),
    "first_player": (4, "select_turn_player"),
}


def _frame(record: dict[str, Any]) -> bytes:
    return base64.b64decode(record["frame_base64"], validate=True)


def _repair_role(
    source: Path, output: Path, role: str, decoder: Path
) -> dict[str, Any]:
    records = [
        json.loads(line) for line in (source / f"{role}.jsonl").open(encoding="utf-8")
    ]
    groups: list[list[dict[str, Any]]] = []
    for record in records:
        if record.get("kind") == "wire_packet" and record.get("direction") == "inbound":
            groups.append([record])
        elif groups:
            groups[-1].append(record)
    requests: list[dict[str, Any]] = []
    prompt_ids: list[int] = []
    automatic = 0
    for group in groups:
        markers = [
            record
            for record in group
            if record.get("kind") in ("prompt", "automatic_pass")
        ]
        outgoing = [
            record
            for record in group
            if record.get("kind") == "wire_packet"
            and record.get("direction") == "outbound"
            and _frame(record)[2] in RESPONSE_TYPES
        ]
        if not markers and not outgoing:
            continue
        if len(markers) != 1 or len(outgoing) != 1:
            raise ValueError(
                f"{role} inbound seq {group[0]['seq']}: decision/response count differs"
            )
        marker, packet = markers[0], _frame(outgoing[0])
        inbound = _frame(group[0])
        if marker["kind"] == "automatic_pass":
            if (
                inbound[2] != 1
                or base64.b64decode(marker["raw_msg_base64"]) != inbound[3:]
            ):
                raise ValueError(
                    f"{role} seq {marker['seq']}: automatic pass frame mismatch"
                )
            automatic += 1
            continue
        prompt = marker["prompt"]
        kind = prompt["kind"]
        if kind in PRE_DUEL:
            expected_type, decision_source = PRE_DUEL[kind]
            if inbound[2] != expected_type:
                raise ValueError(
                    f"{role} seq {marker['seq']}: pre-duel packet mismatch"
                )
            message = b""
        else:
            decision_source = "game_message"
            message = base64.b64decode(marker["raw_msg_base64"], validate=True)
            if inbound[2] != 1 or message != inbound[3:]:
                raise ValueError(
                    f"{role} seq {marker['seq']}: game message frame mismatch"
                )
        ids = [
            candidate["card_id"]
            for candidate in prompt["candidates"]
            if kind == "announce_card" and isinstance(candidate.get("card_id"), int)
        ]
        requests.append(
            {
                "source": decision_source,
                "message_hex": message.hex(),
                "packet_type": packet[2],
                "payload_hex": packet[3:].hex(),
                "allowed_card_ids": ids,
            }
        )
        prompt_ids.append(marker["prompt_id"])
    decoder_result = subprocess.run(
        [str(decoder)],
        input="".join(json.dumps(request) + "\n" for request in requests),
        text=True,
        capture_output=True,
        check=True,
    )
    decoded = [json.loads(line) for line in decoder_result.stdout.splitlines()]
    if len(decoded) != len(requests):
        raise ValueError(
            f"{role}: decoder returned {len(decoded)} results for {len(requests)} prompts"
        )
    repaired: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for prompt_id, request, result in zip(prompt_ids, requests, decoded, strict=True):
        if "action" not in result:
            raise ValueError(
                f"{role} prompt {prompt_id}: decoder error {result.get('error')}"
            )
        repaired[prompt_id] = (request, result["action"])
    seen: set[int] = set()
    removed_errors: list[int] = []
    with (output / f"{role}.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            if (
                record.get("kind") == "error"
                and record.get("code") == "unpaired_response"
            ):
                removed_errors.append(record["seq"])
                continue
            if record.get("kind") == "response":
                prompt_id = record["prompt_id"]
                if prompt_id not in repaired or prompt_id in seen:
                    raise ValueError(
                        f"{role} seq {record['seq']}: missing/duplicate repaired response"
                    )
                request, action = repaired[prompt_id]
                record["packet_type"] = request["packet_type"]
                record["payload_base64"] = base64.b64encode(
                    bytes.fromhex(request["payload_hex"])
                ).decode()
                record["action"] = action
                record.pop("error", None)
                if action["kind"] == "select_places":
                    record["controller_space"] = "raw"
                else:
                    record.pop("controller_space", None)
                seen.add(prompt_id)
            stream.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    if seen != repaired.keys():
        raise ValueError(
            f"{role}: repaired prompt IDs without response records: {repaired.keys() - seen}"
        )
    return {
        "role": role,
        "prompts_repaired": len(repaired),
        "automatic_passes": automatic,
        "removed_recorder_errors": removed_errors,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--decoder",
        type=Path,
        default=root / "out/build/MacOS-Debug/agent_response_decode",
    )
    args = parser.parse_args()
    if not args.decoder.is_file():
        parser.error(f"missing decoder binary: {args.decoder}")
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [
        _repair_role(args.recording, args.output, role, args.decoder)
        for role in ("host", "guest")
    ]
    report = {"status": "repaired", "source": str(args.recording), "roles": reports}
    (args.output / "repair-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
