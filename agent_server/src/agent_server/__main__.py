"""Run one release-local Agent service for one client process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from agent_sdk.contract import ContractError, DecisionRequest, validate_action
from agent_sdk.state import StateDelta
from agent_sdk.test_server import decide as deterministic_decide
from aiohttp import ClientError, ClientSession, ClientTimeout, web

from agent_server.codex_agent import CodexDecisionAgent
from agent_server.codex_mcp_stdio import main as codex_mcp_main
from agent_server.config import load_settings, profile_data_dir
from agent_server.decision_session import DecideFunction
from agent_server.duel_tools import DecisionFailure
from agent_server.http_service import HttpService, load_viewer_token, web_root
from agent_server.model_agent import DecisionAgent
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


def scenario_oracle_url(value: str) -> str:
    """Accept only the local test coordinator's fixed action endpoint."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid scenario oracle URL") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or port is None
        or parsed.path != "/v3/scenario-action"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("scenario oracle must use the local /v3/scenario-action endpoint")
    return value


def scenario_oracle_decide(url: str, token: str) -> DecideFunction:
    """Use a shared scripted oracle while retaining the normal v3 service pipeline."""
    if len(token) < 32:
        raise ValueError("missing or short scenario oracle token")
    queried_hand = False

    async def decide(
        request: DecisionRequest,
        _delta: StateDelta,
        query_client: Any,
    ) -> tuple[dict[str, Any], str]:
        nonlocal queried_hand
        if not queried_hand:
            observation = cast(dict[str, Any], request.data["observation"])
            own_player = observation["self_player"]
            hand = next(
                (
                    zone
                    for zone in cast(list[dict[str, Any]], observation["zones"])
                    if zone["player"] == own_player and zone["name"] == "hand"
                ),
                None,
            )
            if hand is not None:
                result = await query_client(
                    {"kind": "inspect_zone", "player": own_player, "zone": "hand"}
                )
                if result != {"kind": "inspect_zone", "zone": hand}:
                    raise DecisionFailure("scenario_mismatch", "queried hand differs from snapshot")
                queried_hand = True
        deadline = cast(int, request.data["deadline_unix_ms"])
        remaining = (deadline - time.time() * 1000) / 1000
        if remaining <= 0:
            raise DecisionFailure("timeout", "scenario decision deadline expired")
        try:
            async with ClientSession(timeout=ClientTimeout(total=remaining)) as session:
                async with session.post(
                    url,
                    json=request.data,
                    headers={"Authorization": f"Bearer {token}"},
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise DecisionFailure(
                            "scenario_mismatch", f"scenario oracle returned HTTP {response.status}"
                        )
                    payload_value: object = await response.json()
        except (ClientError, TimeoutError, ValueError) as exc:
            raise DecisionFailure("scenario_mismatch", "scenario oracle unavailable") from exc
        if not isinstance(payload_value, dict):
            raise DecisionFailure("scenario_mismatch", "scenario oracle response is invalid")
        payload = cast(dict[str, Any], payload_value)
        if (
            payload.get("schema_version") != 3
            or not isinstance(payload.get("reason"), str)
            or not isinstance(payload.get("action"), dict)
        ):
            raise DecisionFailure("scenario_mismatch", "scenario oracle response is invalid")
        try:
            action = validate_action(request, payload["action"])
        except ContractError as exc:
            raise DecisionFailure("scenario_mismatch", "scenario oracle action is invalid") from exc
        return action, cast(str, payload["reason"])

    return decide


async def serve(profile: str, *, offline: bool = False, scenario_oracle: str | None = None) -> None:
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
        # A client may restart its child service while connections to the old
        # process remain in TIME_WAIT. This still rejects an active listener.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
        codex_agent: CodexDecisionAgent | None = None
        if offline:
            decide = (
                scenario_oracle_decide(
                    scenario_oracle, os.environ.get("YGOPRO_AGENT_E2E_SCENARIO_TOKEN", "")
                )
                if scenario_oracle is not None
                else offline_decide
            )
        elif settings.backend == "codex":
            codex_agent = CodexDecisionAgent(settings, storage, skills, data_dir)
            probe_started = time.perf_counter()
            probe_ok = False
            try:
                async with asyncio.timeout(settings.server.startup_timeout_seconds):
                    await codex_agent.start()
                probe_ok = True
            finally:
                print(
                    json.dumps(
                        {
                            "event": "codex_start_timing",
                            "duration_ms": round((time.perf_counter() - probe_started) * 1000, 2),
                            "status": "completed" if probe_ok else "failed",
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            decide = codex_agent.decide
        else:
            decision_agent = DecisionAgent(settings, storage, skills)
            probe_started = time.perf_counter()
            probe_ok = False
            try:
                await decision_agent.probe()
                probe_ok = True
            finally:
                print(
                    json.dumps(
                        {
                            "event": "model_probe_timing",
                            "duration_ms": round((time.perf_counter() - probe_started) * 1000, 2),
                            "status": "completed" if probe_ok else "failed",
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            decide = decision_agent.decide
        runner: web.AppRunner | None = None
        try:
            service = HttpService(
                settings,
                storage,
                skills,
                decide,
                profile=profile,
                nonce=nonce,
                client_token=token,
                viewer_token=load_viewer_token(data_dir),
                on_duel_finished=codex_agent.finish_duel if codex_agent is not None else None,
            )
            runner = web.AppRunner(service.app(), access_log=None)
            await runner.setup()
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
            if runner is not None:
                await runner.cleanup()
            if codex_agent is not None:
                await codex_agent.close()


async def view_only(profile: str, port: int) -> None:
    root = release_root()
    settings = load_settings(root, profile, offline=True)
    data_dir = profile_data_dir(root, settings, profile)
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
    parser.add_argument("--scenario-oracle", help=argparse.SUPPRESS)
    parser.add_argument(
        "--view-only", action="store_true", help="serve read-only history without a client or model"
    )
    parser.add_argument("--port", type=int, help="explicit port for --view-only")
    parser.add_argument(
        "--delete-duel", action="store_true", help="delete one finished duel locally"
    )
    parser.add_argument("--session-id", help="session ID for --delete-duel")
    parser.add_argument("--duel-id", help="duel ID for --delete-duel")
    parser.add_argument(
        "--check-resources", action="store_true", help="check packaged skills and card DB"
    )
    parser.add_argument("--codex-mcp-stdio", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--check-codex-runtime", action="store_true", help="check bundled Codex runtime offline"
    )
    parser.add_argument("--init-codex", action="store_true", help="initialize Codex ChatGPT login")
    parser.add_argument(
        "--device-code", action="store_true", help="use device code for Codex login"
    )
    args = parser.parse_args()
    try:
        if args.scenario_oracle is not None:
            if not args.offline:
                parser.error("--scenario-oracle requires --offline")
            args.scenario_oracle = scenario_oracle_url(args.scenario_oracle)
        if args.codex_mcp_stdio:
            codex_mcp_main()
            return
        if args.check_codex_runtime:
            from codex_cli_bin import bundled_codex_path  # pyright: ignore[reportMissingTypeStubs]
            from openai_codex import Codex, CodexConfig

            binary = bundled_codex_path()
            if not binary.is_file():
                raise ValueError("bundled Codex runtime is missing")
            version = subprocess.run(
                [str(binary), "--version"], capture_output=True, text=True, timeout=10, check=True
            )
            with tempfile.TemporaryDirectory(prefix="ygopro-codex-check-") as directory:
                config = CodexConfig(
                    cwd=directory,
                    env={"CODEX_HOME": directory, "HOME": directory},
                    config_overrides=("project_doc_max_bytes=0",),
                )
                with Codex(config=config) as codex:
                    codex.account()
            print(json.dumps({"status": "ok", "codex_version": version.stdout.strip()}))
            return
        if args.init_codex:
            from agent_server.codex_init import initialize_codex

            initialize_codex(
                release_root(),
                args.config,
                load_settings(release_root(), args.config),
                device_code=args.device_code,
            )
            return
        if args.device_code:
            parser.error("--device-code requires --init-codex")
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
            if not args.session_id or not args.duel_id or args.view_only:
                parser.error("--delete-duel requires --session-id and --duel-id")
            delete_duel(args.config, args.session_id, args.duel_id)
            return
        if args.view_only:
            if args.port is None:
                parser.error("--view-only requires --port")
            asyncio.run(view_only(args.config, args.port))
            return
        if args.port is not None:
            parser.error("--port requires --view-only")
        asyncio.run(serve(args.config, offline=args.offline, scenario_oracle=args.scenario_oracle))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"agent-server: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
