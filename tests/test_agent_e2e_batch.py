"""Batch replay keeps running after a failed scenario and reports every case."""

from __future__ import annotations

import argparse
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class BatchReplayTests(unittest.TestCase):
    def test_batch_reports_all_cases_in_sorted_order(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        runner = runpy.run_path(str(repository / "tools/agent-e2e.py"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client").write_bytes(b"fixture")
            (root / "cards.cdb").write_bytes(b"fixture")
            for name in ("z-failed", "a-passed", "m-random"):
                path = root / "scenarios" / name / "scenario.yaml"
                path.parent.mkdir(parents=True)
                path.write_text("fixture\n", encoding="utf-8")
                for artifact in ("host.ydk", "guest.ydk", "goal.md", "README.md"):
                    (path.parent / artifact).write_text("fixture\n", encoding="utf-8")
            incomplete = root / "scenarios" / "b-incomplete" / "scenario.yaml"
            incomplete.parent.mkdir(parents=True)
            incomplete.write_text("fixture\n", encoding="utf-8")
            args = argparse.Namespace(
                scenario_dir="scenarios",
                gui=False,
                step_delay=None,
                record_output=None,
                games=None,
                host_deck=None,
                guest_deck=None,
                report_output=None,
                deck="deck/test/test.ydk",
                agent_v3_offline=False,
                protocol="v3",
                timeout=30,
                client="client",
                cards_db="cards.cdb",
            )
            commands: list[str] = []

            def load_scenario(path: Path) -> SimpleNamespace:
                return SimpleNamespace(
                    random_target={} if path.parent.name == "m-random" else None
                )

            def run_child(command: list[str], **_kwargs: object) -> SimpleNamespace:
                scenario = Path(command[command.index("--scenario") + 1])
                commands.append(scenario.parent.name)
                report_path = Path(command[command.index("--report-output") + 1])
                passed = scenario.parent.name == "a-passed"
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "passed" if passed else "failed",
                            "error": None if passed else "scenario mismatch",
                            "diagnostic_dir": str(
                                root / "diagnostics" / scenario.parent.name
                            ),
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0 if passed else 1)

            with (
                patch("agent_sdk.scenario.Scenario.load", side_effect=load_scenario),
                patch("subprocess.run", side_effect=run_child),
            ):
                result = runner["run_scenario_batch"](
                    args, root, argparse.ArgumentParser()
                )
            self.assertEqual(result, 1)
            self.assertEqual(commands, ["a-passed", "z-failed"])
            reports = list(
                (root / "out" / "agent-e2e-runs").glob("batch-*/batch-report.json")
            )
            self.assertEqual(len(reports), 1)
            summary = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(
                summary["counts"], {"passed": 1, "failed": 2, "unsupported": 1}
            )
            self.assertEqual(
                [item["scenario"] for item in summary["scenarios"]],
                [
                    "a-passed/scenario.yaml",
                    "b-incomplete/scenario.yaml",
                    "m-random/scenario.yaml",
                    "z-failed/scenario.yaml",
                ],
            )
            self.assertEqual(summary["scenarios"][0]["exit_code"], 0)
            self.assertIn("missing host.ydk", summary["scenarios"][1]["error"])
            self.assertEqual(summary["scenarios"][2]["status"], "unsupported")
            self.assertEqual(summary["scenarios"][3]["error"], "scenario mismatch")


if __name__ == "__main__":
    unittest.main()
