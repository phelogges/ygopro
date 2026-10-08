"""Profile-local configuration and data paths."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_server.config import ModelSettings, load_settings, profile_data_dir

ROOT = Path(__file__).resolve().parents[2]


class ProfileDataTests(unittest.TestCase):
    def test_profiles_isolate_data(self) -> None:
        settings = load_settings(ROOT, offline=True)
        base = ROOT / settings.storage.directory
        self.assertEqual(profile_data_dir(ROOT, settings, "host"), base / "host")
        self.assertEqual(profile_data_dir(ROOT, settings, "guest"), base / "guest")
        self.assertNotEqual(
            profile_data_dir(ROOT, settings, "host"), profile_data_dir(ROOT, settings, "guest")
        )
        with self.assertRaises(ValueError):
            profile_data_dir(ROOT, settings, "../host")

    def test_profile_symlink_is_rejected(self) -> None:
        settings = load_settings(ROOT, offline=True)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            data_dir = Path(directory)
            settings.storage.directory = str(data_dir.relative_to(ROOT))
            (data_dir / "host").symlink_to(data_dir / "guest", target_is_directory=True)
            with self.assertRaises(ValueError):
                profile_data_dir(ROOT, settings, "host")

    def test_retention_defaults(self) -> None:
        settings = load_settings(ROOT, offline=True)
        self.assertEqual(settings.storage.retention_days, 30)
        self.assertEqual(settings.storage.max_bytes, 2 * 1024 * 1024 * 1024)

    def test_forced_tool_choice_default_and_override(self) -> None:
        model = ModelSettings.model_validate(
            {
                "base_url": "https://example.test/v1",
                "name": "test-model",
                "api_key_env": "TEST_KEY",
                "context_window_tokens": 4096,
            }
        )
        self.assertTrue(model.supports_forced_tool_choice)
        self.assertFalse(
            model.model_copy(
                update={"supports_forced_tool_choice": False}
            ).supports_forced_tool_choice
        )

    def test_reasoning_configuration_and_none_summary(self) -> None:
        base = {
            "base_url": "https://example.test/v1",
            "name": "test-model",
            "api_key_env": "TEST_KEY",
            "context_window_tokens": 4096,
        }
        default = ModelSettings.model_validate(base)
        self.assertEqual(default.reasoning_effort, "auto")
        self.assertEqual(default.effective_reasoning_summary, "auto")
        disabled = ModelSettings.model_validate({**base, "reasoning_effort": "none"})
        self.assertEqual(disabled.effective_reasoning_summary, "off")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            ModelSettings.model_validate(
                {**base, "reasoning_effort": "none", "reasoning_summary": "detailed"}
            )


if __name__ == "__main__":
    unittest.main()
