"""Start the macOS development client with its local Agent child service."""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "out/build/MacOS-Debug/gframe/ygopro"
SERVICE = ROOT / "agent_server/.venv/bin/agent-server"
SECRET_FILE = ROOT / ".agents/data/agent.env"


def api_key_from_file(name: str) -> str:
    if not SECRET_FILE.is_file():
        raise ValueError(f"missing local secret file: {SECRET_FILE}")
    found: str | None = None
    for raw in SECRET_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key.strip() != name or found is not None:
            raise ValueError(f"agent.env must contain only one {name}=... entry")
        found = value.strip().strip("\"'")
    if not found:
        raise ValueError(f"agent.env does not contain {name}")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="config", help=".agents/<profile>.toml")
    parser.add_argument(
        "--check", action="store_true", help="validate local inputs without launching"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.profile):
        parser.error("invalid Agent profile name")

    profile_file = ROOT / ".agents" / f"{args.profile}.toml"
    if not profile_file.is_file():
        parser.error(f"missing Agent configuration: {profile_file}")
    with profile_file.open("rb") as stream:
        config = tomllib.load(stream)
    backend = config.get("backend", "pydantic_ai")
    if backend not in ("pydantic_ai", "codex"):
        parser.error("backend must be pydantic_ai or codex")
    backends = config.get("backends")
    if not isinstance(backends, dict):
        parser.error(
            "configuration must contain [backends.pydantic_ai] or [backends.codex]"
        )
    if "model" in config:
        parser.error("legacy [model] must migrate to [backends.pydantic_ai]")
    for path in (
        CLIENT,
        SERVICE,
        ROOT / "cards.cdb",
        ROOT / ".agents/prompts/duel_system.md",
    ):
        if not path.is_file():
            parser.error(f"missing development resource: {path}")
    if not os.access(CLIENT, os.X_OK) or not os.access(SERVICE, os.X_OK):
        parser.error("client and Agent service must be executable")
    key_name = None
    api_key = None
    if backend == "pydantic_ai":
        model = backends.get("pydantic_ai")
        key_name = model.get("api_key_env") if isinstance(model, dict) else None
        if not isinstance(key_name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", key_name
        ):
            parser.error(
                "backends.pydantic_ai.api_key_env must name an environment variable"
            )
        try:
            api_key = os.environ.get(key_name) or api_key_from_file(key_name)
        except (OSError, UnicodeError, ValueError) as exc:
            parser.error(str(exc))
    elif not isinstance(backends.get("codex"), dict):
        parser.error("codex backend requires [backends.codex]")
    elif backends["codex"].get("auth", "chatgpt") != "chatgpt":
        parser.error("codex backend only supports ChatGPT login")

    if args.check:
        print(f"Agent client inputs ready: profile={args.profile}, client={CLIENT}")
        return

    log_dir = ROOT / "out/agent-live"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"agent-client-{timestamp}-{os.getpid()}.jsonl"
    environment = os.environ.copy()
    environment.update(
        {
            "YGOPRO_AGENT_ENABLE": "1",
            "YGOPRO_AGENT_PROTOCOL": "v3",
            "YGOPRO_AGENT_CONFIG": args.profile,
            "YGOPRO_AGENT_SERVER_EXECUTABLE": str(SERVICE),
            "YGOPRO_AGENT_LOG_PATH": str(log_path),
        }
    )
    if key_name is not None and api_key is not None:
        environment[key_name] = api_key
    environment.pop("YGOPRO_AGENT_E2E_ROLE", None)
    print(f"Starting Agent client; diagnostic log: {log_path}", flush=True)
    os.chdir(ROOT)
    os.execve(CLIENT, [str(CLIENT)], environment)


if __name__ == "__main__":
    main()
