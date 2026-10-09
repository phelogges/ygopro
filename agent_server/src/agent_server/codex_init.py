"""Interactive, profile-local ChatGPT login for the Codex backend."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from agent_server.config import ServiceSettings, profile_data_dir


def initialize_codex(
    root: Path, profile: str, settings: ServiceSettings, *, device_code: bool = False
) -> None:
    """Check the isolated Codex account and log in only when necessary.

    This does not create or rewrite codex_home/config.toml. The official SDK
    selects its matching bundled CLI runtime.
    """
    if settings.backend != "codex":
        raise ValueError("Codex initialization requires backend = 'codex'")

    try:
        from openai_codex import Codex, CodexConfig
    except ImportError as exc:
        raise RuntimeError("openai-codex is not installed in the Agent service") from exc

    profile_dir = profile_data_dir(root, settings, profile)
    codex_dir = profile_dir / "codex"
    codex_home, workspace = codex_dir / "codex_home", codex_dir / "workspace"
    for path in (profile_dir, codex_dir, codex_home, workspace):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Codex runtime directory must stay inside the release root")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    (workspace / ".ygopro-agent-root").touch(exist_ok=True)
    user_config = codex_home / "config.toml"
    if user_config.is_symlink():
        raise ValueError("Codex config must not be a symlink")
    if user_config.exists():
        with user_config.open("rb") as stream:
            configured = tomllib.load(stream)
        allowed = {"model", "model_reasoning_effort", "model_reasoning_summary"}
        disallowed = set(configured) - allowed
        if disallowed:
            raise ValueError(
                "Codex config contains unsupported runtime keys: " + ", ".join(sorted(disallowed))
            )
    env = os.environ.copy()
    env.update({"CODEX_HOME": str(codex_home), "HOME": str(codex_home)})
    for name in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_API_KEY"):
        env[name] = ""
    config = CodexConfig(
        cwd=str(workspace),
        env=env,
        config_overrides=(
            'approval_policy="never"',
            'sandbox_mode="read-only"',
            'web_search="disabled"',
            "project_doc_max_bytes=0",
            'project_root_markers=[".ygopro-agent-root"]',
            "features.shell_tool=false",
            "features.unified_exec=false",
            "features.apps=false",
            "features.hooks=false",
            "features.goals=false",
            "agents.enabled=false",
        ),
    )
    with Codex(config=config) as codex:
        account = codex.account().account
        if account is not None and account.root.type == "chatgpt":
            print(f"Codex ChatGPT account is already signed in: {codex_home}")
            return
        if account is not None:
            raise ValueError("Codex profile has non-ChatGPT authentication; use a fresh profile")
        if device_code:
            login = codex.login_chatgpt_device_code()
            print(f"Open {login.verification_url} and enter code {login.user_code}", flush=True)
        else:
            login = codex.login_chatgpt()
            print(f"Open this URL to sign in to Codex: {login.auth_url}", flush=True)
        try:
            result = login.wait()
        except KeyboardInterrupt:
            login.cancel()
            raise
        verified = codex.account().account
        if not result.success or verified is None or verified.root.type != "chatgpt":
            raise RuntimeError("Codex ChatGPT login did not complete")
        print(f"Codex ChatGPT login completed: {codex_home}")
