#!/usr/bin/env python3
"""Compile paired manual-client JSONL captures into a scenario draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_sdk" / "src"))

from agent_sdk.recording_compiler import compile_recording


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cards-db", type=Path)
    parser.add_argument(
        "--analysis-draft",
        action="store_true",
        help="emit an explicitly unverified draft when random events or room settings prevent replay",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        help="reviewed ordinal choices (default: RECORDING/overrides.json)",
    )
    args = parser.parse_args()
    report = compile_recording(
        args.recording, args.output, args.cards_db, args.overrides, args.analysis_draft
    )
    if report["status"] == "draft_unverified":
        print(f"未验证草稿：{args.output / 'scenario.unverified.yaml'}")
        print(f"不可复现条件：{len(report['blockers'])} 项，详见 compile-report.json")
        return 0
    if report["status"] != "compiled":
        print(f"录制无法编译：{report['errors'][0]}", file=sys.stderr)
        return 1
    print(f"场景草稿：{args.output / 'scenario.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
