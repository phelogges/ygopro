#!/usr/bin/env python3
"""Record a deterministic manual LAN duel and verify the generated scenario."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROLES = ("host", "guest")
ROOM_REQUIREMENTS = {
    "mode": 0,
    "start_hand": 5,
    "start_lp": 8000,
    "draw_count": 1,
    "time_limit": 0,
}


class RecordingFailure(RuntimeError):
    def __init__(
        self, status: str, message: str, *, close_clients: bool = False
    ) -> None:
        super().__init__(message)
        self.status = status
        self.close_clients = close_clients


@dataclass
class RecordingTail:
    path: Path
    offset: int = 0
    pending: bytes = b""
    last_seq: int = 0

    def poll(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        with self.path.open("rb") as source:
            source.seek(self.offset)
            chunk = source.read()
            self.offset = source.tell()
        parts = (self.pending + chunk).split(b"\n")
        self.pending = parts.pop()
        result: list[dict[str, Any]] = []
        for line in parts:
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RecordingFailure(
                    "incomplete", f"{self.path.name}: 日志行损坏：{exc}"
                ) from exc
            if not isinstance(record, dict) or type(record.get("seq")) is not int:
                raise RecordingFailure("incomplete", f"{self.path.name}: 日志记录无效")
            if record["seq"] <= self.last_seq:
                raise RecordingFailure(
                    "incomplete", f"{self.path.name}: 日志序号未递增"
                )
            self.last_seq = record["seq"]
            result.append(record)
        return result


@dataclass
class CaptureState:
    rooms: dict[str, dict[str, Any]] = field(default_factory=dict)
    decks: set[str] = field(default_factory=set)
    started: set[str] = field(default_factory=set)
    ends: dict[str, str] = field(default_factory=dict)
    terminal_since: float | None = None
    warned: set[str] = field(default_factory=set)
    replay_pending: set[str] = field(default_factory=set)
    last_events: dict[str, dict[str, Any]] = field(default_factory=dict)

    def observe(self, role: str, record: dict[str, Any], now: float) -> None:
        kind = record.get("kind")
        self.last_events[role] = {"kind": kind, "seq": record["seq"]}
        if kind == "room_joined":
            self.rooms[role] = record
            if record.get("no_shuffle_deck") not in (True, 1):
                raise RecordingFailure(
                    "config_failed",
                    f"{role}: 未勾选「不洗牌」；录制只接受确定性房间",
                    close_clients=True,
                )
            for key, expected in ROOM_REQUIREMENTS.items():
                if record.get(key) != expected:
                    raise RecordingFailure(
                        "config_failed",
                        f"{role}: {key}={record.get(key)!r}，要求 {expected}",
                    )
            print(f"{role}: 已入房，确定性房间参数通过", flush=True)
            if len(self.rooms) == len(ROLES):
                keys = (*ROOM_REQUIREMENTS, "no_shuffle_deck", "no_check_deck")
                if any(
                    self.rooms["host"].get(key) != self.rooms["guest"].get(key)
                    for key in keys
                ):
                    raise RecordingFailure(
                        "config_failed", "Host 与 Guest 的房间参数不一致"
                    )
        elif kind == "deck_submitted" and role not in self.decks:
            self.decks.add(role)
            print(f"{role}: 已提交卡组", flush=True)
        elif kind == "duel_start" and role not in self.started:
            if role not in self.rooms:
                raise RecordingFailure("incomplete", f"{role}: 入房检查之前已开始决斗")
            self.started.add(role)
            print(f"{role}: 决斗开始", flush=True)
        elif kind == "duel_end" and role not in self.ends:
            winner = record.get("winner")
            if record.get("win_seen") is not True or winner not in (*ROLES, "draw"):
                raise RecordingFailure(
                    "incomplete", f"{role}: 收到终局，但缺少权威 MSG_WIN"
                )
            self.ends[role] = winner
            self.terminal_since = self.terminal_since or now
            print(f"{role}: 权威终局，胜者 {winner}", flush=True)
        elif kind == "replay_save_pending":
            self.replay_pending.add(role)
            print(f"{role}: 请在窗口中处理是否保存录像", flush=True)
        elif kind == "replay_save_resolved":
            self.replay_pending.discard(role)
            if self.terminal_since is not None:
                self.terminal_since = now
            print(f"{role}: 录像保存提示已处理", flush=True)
        elif kind == "connection_closed" and role not in self.ends:
            raise RecordingFailure(
                "aborted",
                f"{role}: 终局前连接关闭（{record.get('reason', 'unknown')}）",
            )
        elif kind == "diagnostic_log_truncated":
            raise RecordingFailure("incomplete", f"{role}: 录制日志达到大小上限")
        elif kind == "error":
            raise RecordingFailure(
                "incomplete",
                f"{role} seq {record['seq']}: 录制器错误 {record.get('code')}",
            )

    def complete(self) -> bool:
        if len(self.ends) != len(ROLES):
            return False
        if self.ends["host"] != self.ends["guest"]:
            raise RecordingFailure("incomplete", f"双方胜者不一致：{self.ends}")
        return True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_provenance(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        return completed.stdout.strip() if completed.returncode == 0 else None

    return {
        "commit": run("rev-parse", "HEAD"),
        "tracked_worktree_dirty": bool(
            run("status", "--porcelain", "--untracked-files=no")
        ),
    }


def write_manifest(path: Path, manifest: dict[str, Any], **changes: Any) -> None:
    manifest.update(changes)
    manifest["updated_at"] = utc_now()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def close_owned_clients(children: dict[str, subprocess.Popen[bytes]]) -> None:
    for child in children.values():
        if child.poll() is None:
            child.terminate()
    for child in children.values():
        if child.poll() is not None:
            continue
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client", type=Path, default=root / "out/build/MacOS-Debug/gframe/ygopro"
    )
    parser.add_argument("--cards-db", type=Path, default=root / "cards.cdb")
    parser.add_argument("--output", type=Path, help="recording directory")
    parser.add_argument("--name", help="human-readable name stored in the manifest")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--terminal-grace", type=int, default=15)
    parser.add_argument("--verify-timeout", type=int, default=300)
    parser.add_argument("--max-log-mib", type=int, default=100)
    parser.add_argument("--close-clients", action="store_true")
    args = parser.parse_args()
    client = args.client.resolve()
    cards_db = args.cards_db.resolve()
    if not client.is_file() or not cards_db.is_file():
        parser.error("client executable and cards database must exist")
    if args.name is not None and (
        not 1 <= len(args.name.strip()) <= 80
        or any(ord(character) < 32 or character in "/\\" for character in args.name)
    ):
        parser.error("--name must be 1-80 readable characters without path separators")
    if args.name is not None:
        args.name = args.name.strip()
    if (
        args.timeout < 60
        or args.verify_timeout < 10
        or not 1 <= args.terminal_grace <= 300
        or not 1 <= args.max_log_mib <= 4096
    ):
        parser.error("invalid timeout or log size")

    capture_id = uuid.uuid4().hex
    work = (args.output or root / "out/duel-recordings" / capture_id).resolve()
    work.mkdir(parents=True, exist_ok=False)
    manifest_path = work / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "record_id": capture_id,
        "name": args.name,
        "created_at": utc_now(),
        "status": "recording",
        "phase": "starting",
        "launcher_pid": os.getpid(),
        "client": {"sha256": sha256(client), "path": str(client)},
        "cards_db": {"sha256": sha256(cards_db), "path": str(cards_db)},
        "source": git_provenance(root),
        "artifacts": {
            "host_log": "host.jsonl",
            "guest_log": "guest.jsonl",
            "draft": "draft",
            "validation_log": "validation.log",
        },
    }
    write_manifest(manifest_path, manifest)
    children: dict[str, subprocess.Popen[bytes]] = {}
    tails = {role: RecordingTail(work / f"{role}.jsonl") for role in ROLES}
    state = CaptureState()
    environment = os.environ.copy()
    for key in list(environment):
        if key == "YGOPRO_AGENT_ENABLE" or key.startswith("YGOPRO_AGENT_E2E_"):
            environment.pop(key)
    print(f"录制 ID：{capture_id}", flush=True)
    print(f"录制目录：{work}", flush=True)
    if args.name:
        print(f"名称：{args.name}", flush=True)
    close_clients = args.close_clients
    try:
        for role in ROLES:
            child_env = environment | {
                "YGOPRO_DUEL_RECORD_ID": capture_id,
                "YGOPRO_DUEL_RECORD_ROLE": role,
                "YGOPRO_DUEL_RECORD_PATH": str(tails[role].path),
                "YGOPRO_DUEL_RECORD_MAX_BYTES": str(args.max_log_mib * 1024 * 1024),
            }
            with (work / f"{role}.log").open("wb") as output:
                children[role] = subprocess.Popen(
                    [str(client)],
                    cwd=root,
                    env=child_env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
            print(f"{role}: GUI 已启动（PID {children[role].pid}）", flush=True)
        write_manifest(
            manifest_path,
            manifest,
            phase="manual_duel",
            clients={role: child.pid for role, child in children.items()},
        )
        print("请建单局 1v1 房间并勾选「不洗牌」，双方手动完成决斗。", flush=True)
        deadline = time.monotonic() + args.timeout
        while True:
            now = time.monotonic()
            for role in ROLES:
                for record in tails[role].poll():
                    state.observe(role, record, now)
                if (
                    role not in state.warned
                    and tails[role].path.is_file()
                    and tails[role].path.stat().st_size
                    >= args.max_log_mib * 1024 * 1024 * 0.8
                ):
                    state.warned.add(role)
                    print(f"警告：{role} 日志已达到大小上限的 80%", flush=True)
            if len(state.rooms) == len(ROLES) and "room" not in manifest:
                write_manifest(
                    manifest_path,
                    manifest,
                    room={
                        key: state.rooms["host"][key]
                        for key in (
                            *ROOM_REQUIREMENTS,
                            "no_shuffle_deck",
                            "no_check_deck",
                        )
                    },
                )
            if state.complete():
                break
            for role, child in children.items():
                if child.poll() is not None and role not in state.ends:
                    raise RecordingFailure("aborted", f"{role}: 客户端在权威终局前退出")
            if (
                state.terminal_since is not None
                and not state.replay_pending
                and now - state.terminal_since > args.terminal_grace
            ):
                missing = sorted(set(ROLES) - state.ends.keys())
                raise RecordingFailure(
                    "incomplete",
                    f"终局仅到达一方；{', '.join(missing)} 在宽限期内没有终局；"
                    f"双方最后事件 {state.last_events}",
                )
            if now > deadline:
                raise RecordingFailure("aborted", "等待人工决斗结束超时")
            time.sleep(0.2)

        write_manifest(
            manifest_path, manifest, phase="compiling", winner=state.ends["host"]
        )
        draft = work / "draft"
        print("双方权威终局一致；开始编译场景", flush=True)
        compiled = subprocess.run(
            [
                sys.executable,
                str(root / "tools/compile-duel-recording.py"),
                "--recording",
                str(work),
                "--output",
                str(draft),
                "--cards-db",
                str(cards_db),
            ],
            cwd=root,
            env=environment,
            check=False,
        )
        if compiled.returncode:
            report_path = draft / "compile-report.json"
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.is_file()
                else {}
            )
            status = (
                "review_required"
                if report.get("status") == "review_needed"
                else "compile_failed"
            )
            raise RecordingFailure(status, f"场景编译失败；诊断见 {report_path}")

        write_manifest(
            manifest_path, manifest, phase="validating", scenario="draft/scenario.yaml"
        )
        print(f"场景草稿：{draft / 'scenario.yaml'}", flush=True)
        print("开始无头双客户端回放验证", flush=True)
        with (work / "validation.log").open("wb") as output:
            validated = subprocess.run(
                [
                    sys.executable,
                    str(root / "tools/agent-e2e.py"),
                    "--client",
                    str(client),
                    "--cards-db",
                    str(cards_db),
                    "--scenario",
                    str(draft / "scenario.yaml"),
                    "--timeout",
                    str(args.verify_timeout),
                ],
                cwd=root,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
        status = "validated" if validated.returncode == 0 else "validation_failed"
        result = {
            "schema_version": 1,
            "capture_id": capture_id,
            "status": status,
            "scenario": str(draft / "scenario.yaml"),
            "validation_log": str(work / "validation.log"),
            "validation_exit_code": validated.returncode,
        }
        (work / "validation-report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest(manifest_path, manifest, status=status, phase="finished")
        print(
            f"验证结果：{status}；报告：{work / 'validation-report.json'}", flush=True
        )
        return validated.returncode
    except RecordingFailure as exc:
        close_clients = close_clients or exc.close_clients
        write_manifest(
            manifest_path,
            manifest,
            status=exc.status,
            phase="finished",
            reason=str(exc),
            last_events=state.last_events,
            observed_rooms=state.rooms,
        )
        print(f"录制结束：{exc}；原始记录保留在 {work}", file=sys.stderr, flush=True)
        return 1
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        reason = "用户取消" if isinstance(exc, KeyboardInterrupt) else str(exc)
        write_manifest(
            manifest_path,
            manifest,
            status="aborted",
            phase="finished",
            reason=reason,
            last_events=state.last_events,
            observed_rooms=state.rooms,
        )
        print(f"录制中止：{reason}；原始记录保留在 {work}", file=sys.stderr, flush=True)
        return 1
    finally:
        if close_clients:
            close_owned_clients(children)
            print("已关闭本次启动的两个录制客户端", flush=True)
        else:
            print("录制客户端窗口仍在，可自行查看或关闭", flush=True)
        print(f"记录目录：{work}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
