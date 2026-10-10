"""Check every native client game message has an Agent handling disposition."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools/agent-message-coverage.json"
CASE = re.compile(r"\bcase\s+(MSG_[A-Z0-9_]+)\s*:")
DECODED = re.compile(r"\btype\s*==\s*(MSG_[A-Z0-9_]+)\b")
DEFINE = re.compile(r"^#define\s+(MSG_[A-Z0-9_]+)\s+(\d+)\b", re.MULTILINE)
SCOPES = {"duel", "pregame", "out_of_scope", "legacy"}


def audit(root: Path = ROOT) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    native_source = (root / "gframe/duelclient.cpp").read_text(encoding="utf-8")
    agent_source = (root / "gframe/agent_client/agent_controller.cpp").read_text(
        encoding="utf-8"
    )
    definitions: dict[str, int] = {}
    for source in ("ocgcore/common.h", "gframe/network.h"):
        for name, number in DEFINE.findall((root / source).read_text(encoding="utf-8")):
            value = int(number)
            if name in definitions and definitions[name] != value:
                errors.append(f"{name}: conflicting numeric definitions")
            definitions[name] = value

    native = set(CASE.findall(native_source))
    ignored_section = agent_source.split("bool NonessentialMessage(", 1)[1].split(
        "bool CardKnown(", 1
    )[0]
    decoded_section = agent_source.split("void AgentController::RecordEvent(", 1)[
        1
    ].split("nlohmann::json AgentController::BuildObservation(", 1)[0]
    ignored = set(CASE.findall(ignored_section)) & native
    codec_source = (root / "gframe/agent_client/game_event_codec.h").read_text(
        encoding="utf-8"
    )
    registration = codec_source.split("inline bool GameEventMessage(", 1)[1].split(
        "inline std::optional<nlohmann::json> ParseGameEvent(", 1
    )[0]
    registered = set(CASE.findall(registration))
    parsed = set(
        CASE.findall(
            codec_source.split("inline std::optional<nlohmann::json> ParseGameEvent(", 1)[1]
        )
    )
    for name in sorted(registered ^ parsed):
        errors.append(f"{name}: game event registration and parser disagree")
    decoded = (set(DECODED.findall(decoded_section)) | registered) & native

    manifest = json.loads((root / "tools/agent-message-coverage.json").read_text())
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("pending"), list
    ):
        errors.append("coverage manifest: expected schema_version 1 and pending list")
        return {}, errors
    pending: set[str] = set()
    for entry in manifest["pending"]:
        if not isinstance(entry, dict):
            errors.append("coverage manifest: pending item must be an object")
            continue
        name, scope, observation = (
            entry.get("message"),
            entry.get("scope"),
            entry.get("safe_observation"),
        )
        if not isinstance(name, str) or not name.startswith("MSG_"):
            errors.append(f"coverage manifest: invalid message {name!r}")
            continue
        if name in pending:
            errors.append(f"{name}: duplicate pending entry")
        pending.add(name)
        if scope not in SCOPES or not isinstance(observation, str) or not observation:
            errors.append(f"{name}: scope and safe_observation are required")
    for name in sorted(native - definitions.keys()):
        errors.append(f"{name}: native message lacks an active numeric definition")
    for first, second, label in (
        (ignored, decoded, "ignored and decoded"),
        (ignored, pending, "ignored and pending"),
        (decoded, pending, "decoded and pending"),
    ):
        for name in sorted(first & second):
            errors.append(f"{name}: classified as both {label}")
    for name in sorted(native - ignored - decoded - pending):
        errors.append(f"{name}: native message has no Agent classification")
    for name in sorted(pending - native):
        errors.append(f"{name}: pending entry has no native client handler")
    classification = {
        name: (
            "ignored"
            if name in ignored
            else "decoded"
            if name in decoded
            else "pending"
        )
        for name in sorted(native)
        if name in ignored | decoded | pending
    }
    return classification, errors


def main() -> int:
    classification, errors = audit()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    counts = {
        kind: list(classification.values()).count(kind)
        for kind in ("decoded", "ignored", "pending")
    }
    print(f"Agent message coverage: {len(classification)} native messages, {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
