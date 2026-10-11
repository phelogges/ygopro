"""Profile-local configuration and data paths."""

from __future__ import annotations

import runpy
import tempfile
import tomllib
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from agent_server.codex_init import initialize_codex
from agent_server.config import (
    LimitSettings,
    ModelSettings,
    ServiceSettings,
    StorageSettings,
    load_settings,
    model_api_key,
    profile_data_dir,
)

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
        template = tomllib.loads((ROOT / ".agents/config.example.toml").read_text())
        storage = StorageSettings()
        limits = LimitSettings()
        self.assertEqual(storage.retention_days, 30)
        self.assertEqual(storage.max_bytes, 2 * 1024 * 1024 * 1024)
        self.assertEqual(limits.card_lookup_batch_size, 12)
        self.assertEqual(limits.finalization_reserve_requests, 2)
        self.assertEqual(limits.finalization_reserve_seconds, 20)
        for name in ("retention_days", "max_bytes"):
            self.assertEqual(template["storage"][name], getattr(storage, name))
        for name in (
            "card_lookup_batch_size",
            "finalization_reserve_requests",
            "finalization_reserve_seconds",
        ):
            self.assertEqual(template["limits"][name], getattr(limits, name))

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

    def test_backend_switch_keeps_both_config_sections(self) -> None:
        template = tomllib.loads((ROOT / ".agents/config.example.toml").read_text())
        template["backend"] = "codex"
        settings = ServiceSettings.model_validate(template)
        self.assertIsNone(settings.model)
        self.assertIsNotNone(settings.backends.codex)
        self.assertIsNotNone(settings.backends.pydantic_ai)
        assert settings.backends.codex is not None
        assert settings.backends.pydantic_ai is not None
        self.assertEqual(settings.backends.codex.auth, "chatgpt")
        self.assertEqual(settings.backends.pydantic_ai.name, "set-model-name")
        self.assertEqual(settings.backends.pydantic_ai.compaction.target_fraction, 0.60)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "does not use"):
                model_api_key(settings)
        with self.assertRaisesRegex(ValueError, "requires \\[backends.pydantic_ai\\]"):
            ServiceSettings.model_validate(
                {
                    **template,
                    "backend": "pydantic_ai",
                    "backends": {"codex": template["backends"]["codex"]},
                }
            )
        with self.assertRaisesRegex(ValueError, "requires \\[backends.codex\\]"):
            ServiceSettings.model_validate(
                {**template, "backends": {"pydantic_ai": template["backends"]["pydantic_ai"]}}
            )
        with self.assertRaises(ValueError):
            ServiceSettings.model_validate(
                {**template, "model": template["backends"]["pydantic_ai"]}
            )

    def test_only_pydantic_backend_has_compaction_settings(self) -> None:
        template = tomllib.loads((ROOT / ".agents/config.example.toml").read_text())
        template["backends"]["pydantic_ai"]["compaction"]["trigger_fraction"] = 0.80
        settings = ServiceSettings.model_validate(template)
        assert settings.backends.pydantic_ai is not None
        assert settings.backends.codex is not None
        self.assertEqual(settings.backends.pydantic_ai.compaction.trigger_fraction, 0.80)
        with self.assertRaises(ValueError):
            ServiceSettings.model_validate({**template, "compaction": {"trigger_fraction": 0.75}})
        template["backends"]["codex"]["compaction"] = {"trigger_fraction": 0.65}
        with self.assertRaises(ValueError):
            ServiceSettings.model_validate(template)

    def test_selected_backend_controls_placeholder_validation(self) -> None:
        template = (ROOT / ".agents/config.example.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".agents").mkdir()
            profile = root / ".agents/config.toml"
            profile.write_text(template, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "name must be configured"):
                load_settings(root)
            offline_model = load_settings(root, offline=True).model
            assert offline_model is not None
            self.assertEqual(offline_model.name, "offline-test-model")
            profile.write_text(template.replace('backend = "pydantic_ai"', 'backend = "codex"', 1))
            codex = load_settings(root)
            self.assertEqual(codex.backend, "codex")
            self.assertIsNone(codex.model)
            assert codex.backends.pydantic_ai is not None
            self.assertEqual(codex.backends.pydantic_ai.name, "set-model-name")

    def test_release_check_accepts_both_sections_and_rejects_legacy_model(self) -> None:
        check = cast(
            Callable[[Path], None],
            runpy.run_path(str(ROOT / "tools/agent-release.py"))["check_config"],
        )
        template = (ROOT / ".agents/config.example.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "config.toml"
            profile.write_text(template, encoding="utf-8")
            check(profile)
            profile.write_text(template.replace('backend = "pydantic_ai"', 'backend = "codex"', 1))
            check(profile)
            profile.write_text(template.replace("[backends.pydantic_ai]", "[model]", 1))
            with self.assertRaisesRegex(ValueError, "Legacy \\[model\\]"):
                check(profile)

    def test_codex_init_uses_profile_home_without_creating_config(self) -> None:
        template = tomllib.loads((ROOT / ".agents/config.example.toml").read_text())
        template["backend"] = "codex"
        settings = ServiceSettings.model_validate(template)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            settings.storage.directory = str(Path(directory).relative_to(ROOT))
            codex = MagicMock()
            codex.account.return_value.account = SimpleNamespace(
                root=SimpleNamespace(type="chatgpt")
            )
            codex_type = MagicMock()
            codex_type.return_value.__enter__.return_value = codex
            with patch("openai_codex.Codex", codex_type):
                initialize_codex(ROOT, "host", settings)
            config = codex_type.call_args.kwargs["config"]
            codex_home = Path(config.env["CODEX_HOME"])
            self.assertEqual(config.env["HOME"], str(codex_home))
            self.assertEqual(codex_home, Path(directory) / "host/codex/codex_home")
            self.assertFalse((codex_home / "config.toml").exists())
            codex.login_chatgpt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
