"""Process-level checks for the manual duel recording launcher."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools/record-duel.py"


@unittest.skipIf(os.name == "nt", "fake executable uses a POSIX shebang")
class RecordDuelLauncherTests(unittest.TestCase):
    def test_replay_save_dialog_pauses_terminal_grace(self) -> None:
        spec = importlib.util.spec_from_file_location("record_duel_launcher", LAUNCHER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        state = module.CaptureState()
        with redirect_stdout(StringIO()):
            state.observe(
                "host",
                {"kind": "duel_end", "seq": 1, "winner": "host", "win_seen": True},
                10.0,
            )
            state.observe("guest", {"kind": "replay_save_pending", "seq": 1}, 10.0)
            self.assertEqual(state.replay_pending, {"guest"})
            state.observe("guest", {"kind": "replay_save_resolved", "seq": 2}, 45.0)
        self.assertFalse(state.replay_pending)
        self.assertEqual(state.terminal_since, 45.0)

    def run_fake_client(
        self,
        *,
        no_shuffle: bool,
        disconnect: bool,
        scenario_kind: str = "deterministic",
        goal_text: str | None = None,
    ) -> tuple[dict, str, str | None]:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            client = folder / "fake-client"
            client.write_text(
                f"#!{sys.executable}\n"
                "import json, os, time\n"
                "from pathlib import Path\n"
                "role = os.environ['YGOPRO_DUEL_RECORD_ROLE']\n"
                "path = Path(os.environ['YGOPRO_DUEL_RECORD_PATH'])\n"
                "events = [\n"
                " {'kind': 'session', 'record_id': os.environ['YGOPRO_DUEL_RECORD_ID']},\n"
                " {'kind': 'room_joined', 'mode': 0, "
                f"'no_shuffle_deck': {no_shuffle!r}, "
                "'no_check_deck': False, 'start_hand': 5, 'start_lp': 8000, "
                "'draw_count': 1, 'time_limit': 0},\n"
                "]\n"
                f"if {disconnect!r}: events.append({{'kind': 'connection_closed', 'reason': 'eof'}})\n"
                "with path.open('w') as output:\n"
                " for seq, event in enumerate(events, 1):\n"
                "  output.write(json.dumps({**event, 'seq': seq, 'role': role}) + '\\n')\n"
                "  output.flush()\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            client.chmod(0o755)
            cards_db = folder / "cards.cdb"
            cards_db.write_bytes(b"test-only")
            recording = folder / "capture"
            goal = folder / "goal.md"
            if goal_text is not None:
                goal.write_text(goal_text, encoding="utf-8")
            command = [
                sys.executable,
                str(LAUNCHER),
                "--client",
                str(client),
                "--cards-db",
                str(cards_db),
                "--output",
                str(recording),
                "--name",
                "测试（录制）",
                "--scenario-kind",
                scenario_kind,
                "--timeout",
                "60",
                "--close-clients",
            ]
            if goal_text is not None:
                command.extend(("--goal-file", str(goal)))
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            manifest = json.loads(
                (recording / "manifest.json").read_text(encoding="utf-8")
            )
            for pid in manifest["clients"].values():
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            self.assertNotEqual(completed.returncode, 0)
            archived_goal = (
                (recording / "goal.md").read_text(encoding="utf-8")
                if (recording / "goal.md").is_file()
                else None
            )
            return manifest, completed.stdout + completed.stderr, archived_goal

    def test_missing_no_shuffle_closes_both_owned_clients(self) -> None:
        manifest, output, _ = self.run_fake_client(no_shuffle=False, disconnect=False)
        self.assertEqual(manifest["status"], "config_failed")
        self.assertEqual(manifest["name"], "测试（录制）")
        self.assertIn("未勾选「不洗牌」", manifest["reason"])
        self.assertIn("已关闭本次启动的两个录制客户端", output)
        self.assertTrue(manifest["observed_rooms"])

    def test_connection_close_marks_aborted(self) -> None:
        manifest, _, _ = self.run_fake_client(no_shuffle=True, disconnect=True)
        self.assertEqual(manifest["status"], "aborted")
        self.assertIn("连接关闭", manifest["reason"])

    def test_random_goal_is_archived_before_duel_starts(self) -> None:
        goal_text = "## 用户原始描述\n测试一次抛币\n\n## Agent 整理\n检查双方结果\n"
        manifest, _, archived_goal = self.run_fake_client(
            no_shuffle=True,
            disconnect=True,
            scenario_kind="random",
            goal_text=goal_text,
        )
        self.assertEqual(manifest["scenario_kind"], "random")
        self.assertEqual(manifest["goal"]["path"], "goal.md")
        self.assertEqual(archived_goal, goal_text)


if __name__ == "__main__":
    unittest.main()
