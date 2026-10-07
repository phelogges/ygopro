"""Run one release-local Agent service for one client process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from agent_sdk.contract import DecisionRequest
from agent_sdk.state import StateDelta
from agent_sdk.test_server import decide as deterministic_decide
from aiohttp import web

from agent_server.config import load_settings, profile_data_dir
from agent_server.http_service import HttpService, load_viewer_token, web_root
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
    data_dir = profile_data_dir(root, settings, profile)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", settings.server.port))
        sock.listen(128)
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    with (
        closing(sock),
        StateDatabase(
            data_dir / "state.sqlite3",
            checkpoint_interval=settings.storage.checkpoint_interval,
        ) as storage,
    ):
        storage.mark_interrupted_turns()
        storage.prune_finished(settings.storage.retention_days, settings.storage.max_bytes)
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
        try:
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


async def view_only(profile: str, port: int, *, legacy: bool = False) -> None:
    root = release_root()
    settings = load_settings(root, profile, offline=True)
    data_dir = (
        root / settings.storage.directory if legacy else profile_data_dir(root, settings, profile)
    )
    token_path = data_dir / "viewer-token"
    if not token_path.is_file():
        raise ValueError(f"viewer token does not exist: {token_path}")
    if not 1 <= port <= 65535:
        raise ValueError("view-only port must be between 1 and 65535")
    viewer_token = token_path.read_text(encoding="ascii").strip()
    if len(viewer_token) < 32:
        raise ValueError("viewer token file is invalid")
    with StateDatabase(data_dir / "state.sqlite3", read_only=True) as storage:
        service = HttpService(
            settings,
            storage,
            SkillResources(root),
            offline_decide,
            profile=profile,
            nonce="",
            client_token="",
            viewer_token=viewer_token,
            view_only=True,
        )
        runner = web.AppRunner(service.app(), access_log=None)
        await runner.setup()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.listen(32)
            sock.setblocking(False)
            await web.SockSite(runner, sock).start()
            print(f"View only: http://127.0.0.1:{port}/view", flush=True)
            print(f"Viewer token file: {token_path}", flush=True)
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


def delete_duel(profile: str, session_id: str, duel_id: str) -> None:
    root = release_root()
    settings = load_settings(root, profile, offline=True)
    data_dir = profile_data_dir(root, settings, profile)
    with StateDatabase(data_dir / "state.sqlite3") as storage:
        after = 0
        finished = False
        while True:
            page = storage.get_traces(session_id, duel_id, after_id=after, limit=1000)
            if any(item["kind"] == "duel_finished" for item in page):
                finished = True
                break
            if not page:
                break
            after = int(page[-1]["id"])
        if not finished:
            raise ValueError("only a finished duel can be deleted")
        if not storage.delete_duel(session_id, duel_id):
            raise ValueError("duel does not exist")
    print(f"Deleted duel {duel_id} from profile {profile}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local YGOPro Agent service")
    parser.add_argument("--config", default="config", help="profile basename in .agents/")
    parser.add_argument("--offline", action="store_true", help="deterministic protocol fixture")
    parser.add_argument(
        "--view-only", action="store_true", help="serve read-only history without a client or model"
    )
    parser.add_argument("--port", type=int, help="explicit port for --view-only")
    parser.add_argument(
        "--legacy", action="store_true", help="view the pre-profile database read-only"
    )
    parser.add_argument(
        "--delete-duel", action="store_true", help="delete one finished duel locally"
    )
    parser.add_argument("--session-id", help="session ID for --delete-duel")
    parser.add_argument("--duel-id", help="duel ID for --delete-duel")
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
            for name in ("index.html", "app.js", "style.css"):
                if not (web_root() / name).is_file():
                    raise ValueError(f"missing packaged viewer resource: {name}")
            print(json.dumps({"status": "ok", "database_sha256": skills.database_sha256}))
            return
        if args.delete_duel:
            if not args.session_id or not args.duel_id or args.view_only or args.legacy:
                parser.error("--delete-duel requires --session-id and --duel-id")
            delete_duel(args.config, args.session_id, args.duel_id)
            return
        if args.view_only:
            if args.port is None:
                parser.error("--view-only requires --port")
            asyncio.run(view_only(args.config, args.port, legacy=args.legacy))
            return
        if args.port is not None or args.legacy:
            parser.error("--port and --legacy require --view-only")
        asyncio.run(serve(args.config, offline=args.offline))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"agent-server: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
