"""Release layout checks using small, constructed resources."""

from __future__ import annotations

import json
import runpy
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

RELEASE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "tools/agent-release.py")
)


class ReleaseVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.release = Path(self.temporary.name) / "release"
        self.release.mkdir()
        for name in RELEASE["REQUIRED_TREES"]:
            (self.release / name).mkdir()
        for name in ("deck", "replay", "single"):
            (self.release / name).mkdir()
        for name in ("ygopro", "agent-server"):
            binary = self.release / name
            binary.write_bytes(b"example executable")
            binary.chmod(0o755)
        for name in ("strings.conf", "lflist.conf", "system.conf"):
            (self.release / name).write_text("example\n", encoding="utf-8")
        with sqlite3.connect(self.release / "cards.cdb") as connection:
            connection.execute("CREATE TABLE datas (id INTEGER)")
            connection.execute("CREATE TABLE texts (id INTEGER)")
        agent = self.release / ".agents"
        agent.mkdir()
        (agent / "config.toml").write_text(
            '[model]\napi_key_env = "EXAMPLE_API_KEY"\n'
            '[storage]\ndirectory = ".agents/data"\n',
            encoding="utf-8",
        )
        for name, files in RELEASE["SKILL_FILES"].items():
            skill = self.release / ".agents/skills" / name
            for filename in files:
                path = skill / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("example\n", encoding="utf-8")
            for tree in RELEASE["SKILL_TREES"][name]:
                (skill / tree).mkdir()
        manifest = {
            "schema_version": 1,
            "platform": "macos",
            "sha256": {
                name: RELEASE["digest"](self.release / name)
                for name in RELEASE["HASHED_FILES"]
            },
        }
        (self.release / RELEASE["MANIFEST_PATH"]).write_text(json.dumps(manifest))

    def test_valid_release_and_zip_keep_empty_directories(self) -> None:
        RELEASE["verify_release"](self.release)
        archive = Path(self.temporary.name) / "release.zip"
        RELEASE["make_zip"](self.release, archive)
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn("release/deck/", bundle.namelist())
            self.assertIn("release/.agents/config.toml", bundle.namelist())

    def test_tampered_database_rejected(self) -> None:
        (self.release / "cards.cdb").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            RELEASE["verify_release"](self.release)

    def test_local_data_rejected(self) -> None:
        (self.release / ".agents/data").mkdir()
        with self.assertRaisesRegex(ValueError, "unexpected files"):
            RELEASE["verify_release"](self.release)

    def test_legacy_agent_directory_rejected(self) -> None:
        (self.release / ".agent").mkdir()
        with self.assertRaisesRegex(ValueError, "Forbidden release content"):
            RELEASE["verify_release"](self.release)


if __name__ == "__main__":
    unittest.main()
