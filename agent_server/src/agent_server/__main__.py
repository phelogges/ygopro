"""Run one release-local Agent service for one client process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import DecisionRequest
from agent_sdk.state import StateDelta
from agent_sdk.test_server import decide as deterministic_decide
from aiohttp import web

from agent_server.config import load_settings
from agent_server.http_service import HttpService, load_viewer_token
from agent_server.model_agent import DecisionAgent, DecisionFailure
from agent_server.skills import SkillResources
from agent_server.storage import StateDatabase


def release_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


async def offline_decide(
    request: DecisionRequest,
    _delta: StateDelta,
    _query_client: Any,
) -> tuple[dict[str, Any], str]:
    """A deterministic transport fixture, enabled only by an explicit CLI flag."""
    try:
        response = deterministic_decide(request.data, str(request.data["database_sha256"]))
    except ValueError as exc:
        raise DecisionFailure("unsupported_prompt", str(exc)) from exc
    return cast(dict[str, Any], response["action"]), "离线协议测试"


async def serve(profile: str, *, offline: bool = False) -> None:
    root = release_root()
    settings = load_settings(root, profile, offline=offline)
    token = os.environ.get("YGOPRO_AGENT_BOOT_TOKEN", "")
    nonce = os.environ.get("YGOPRO_AGENT_BOOT_NONCE", "")
    if len(token) < 32 or len(nonce) < 16:
        raise ValueError("missing or short client boot token/nonce")
    skills = SkillResources(root)
    data_dir = root / settings.storage.directory
    with StateDatabase(
        data_dir / "state.sqlite3",
        checkpoint_interval=settings.storage.checkpoint_interval,
    ) as storage:
        if offline:
            decide = offline_decide
        else:
            decision_agent = DecisionAgent(settings, storage, skills)
            await decision_agent.probe()
            decide = decision_agent.decide
        service = HttpService(
            settings,
            storage,
            skills,
            decide,
            profile=profile,
            nonce=nonce,
            client_token=token,
            viewer_token=load_viewer_token(data_dir),
        )
        runner = web.AppRunner(service.app(), access_log=None)
        await runner.setup()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            sock.bind(("127.0.0.1", settings.server.port))
            sock.listen(128)
            sock.setblocking(False)
            site = web.SockSite(runner, sock)
            await site.start()
            print(
                json.dumps(
                    {
                        "schema_version": 3,
                        "port": settings.server.port,
                        "nonce": nonce,
                        "decision_timeout_ms": settings.limits.decision_seconds * 1000,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for name in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(name, stop.set)
                except NotImplementedError:
                    pass
            await stop.wait()
        finally:
            await runner.cleanup()
            sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local YGOPro Agent service")
    parser.add_argument("--config", default="config", help="profile basename in .agents/")
    parser.add_argument("--offline", action="store_true", help="deterministic protocol fixture")
    parser.add_argument(
        "--check-resources", action="store_true", help="check packaged skills and card DB"
    )
    args = parser.parse_args()
    try:
        if args.check_resources:
            skills = SkillResources(release_root())
            skills.rulebook_index()
            skills.rulebook_section("game-progression")
            skills.card_by_id(89631139)
            print(json.dumps({"status": "ok", "database_sha256": skills.database_sha256}))
            return
        asyncio.run(serve(args.config, offline=args.offline))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"agent-server: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
