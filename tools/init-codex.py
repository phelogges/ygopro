"""Initialize a profile-local Codex ChatGPT login for development."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent_server.codex_init import initialize_codex
from agent_server.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="config", help=".agents/<profile>.toml")
    parser.add_argument(
        "--device-code", action="store_true", help="use the device-code login flow"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        settings = load_settings(root, args.profile)
        initialize_codex(root, args.profile, settings, device_code=args.device_code)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"init-codex: {exc}\n")


if __name__ == "__main__":
    main()
