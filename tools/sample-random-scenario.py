#!/usr/bin/env python3
"""Sample one reviewed random scenario without masking a failed duel by retrying."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "agent_sdk/src"))
    from agent_sdk.scenario import Scenario  # pyright: ignore[reportMissingImports]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--cards-db", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--protocol", choices=("v2", "v3"), default="v3")
    parser.add_argument("--report-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--max-runs", type=int, help="override scenario random_target.max_runs"
    )
    args = parser.parse_args()
    scenario = Scenario.load(args.scenario)
    if scenario.random_target is None:
        parser.error("sampling requires a reviewed schema v2 random scenario")
    coverage = scenario.random_target.get("coverage", [])
    if not coverage and args.max_runs is not None:
        parser.error("--max-runs requires explicit random_target.coverage")
    limit = (
        (
            args.max_runs
            if args.max_runs is not None
            else scenario.random_target.get("max_runs", 20)
        )
        if coverage
        else 1
    )
    if not 1 <= limit <= 100:
        parser.error("max runs must be between 1 and 100")
    work = (
        root
        / "out/agent-e2e-runs"
        / f"random-samples-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    )
    work.mkdir(parents=True, exist_ok=False)
    observed: set[str] = set()
    attempts: list[dict[str, object]] = []
    status = "coverage_incomplete"
    expected = {
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        for result in coverage
    }
    try:
        for index in range(1, limit + 1):
            report_path = work / f"run-{index}.json"
            command = [
                sys.executable,
                str(root / "tools/agent-e2e.py"),
                "--scenario",
                str(args.scenario.resolve()),
                "--timeout",
                str(args.timeout),
                "--protocol",
                args.protocol,
                "--report-output",
                str(report_path),
            ]
            if args.client:
                command.extend(("--client", str(args.client.resolve())))
            if args.cards_db:
                command.extend(("--cards-db", str(args.cards_db.resolve())))
            with (work / f"run-{index}.log").open("wb") as output:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.is_file()
                else {}
            )
            case = (report.get("result") or {}).get("random_case")
            attempts.append(
                {
                    "run": index,
                    "exit_code": completed.returncode,
                    "report": str(report_path),
                    "diagnostic_dir": report.get("diagnostic_dir"),
                    "case": case,
                    "error": report.get("error"),
                }
            )
            if completed.returncode or not isinstance(case, str):
                status = "failed"
                break
            observed.add(case)
            if not expected or expected.issubset(observed):
                status = "covered" if expected else "single_passed"
                break
    finally:
        result = {
            "schema_version": 1,
            "status": status,
            "agent_http_protocol": args.protocol,
            "diagnostic_dir": str(work),
            "scenario": str(args.scenario.resolve()),
            "expected_cases": sorted(expected),
            "observed_cases": sorted(observed),
            "max_runs": limit,
            "attempts": attempts,
        }
        output_path = args.report_output or work / "sampling-report.json"
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{status}: {output_path}", flush=True)
    return 0 if status in ("covered", "single_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
