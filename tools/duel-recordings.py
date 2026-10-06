#!/usr/bin/env python3
"""List and explicitly remove local manual-duel recordings."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

RECORD_ID = re.compile(r"[0-9a-f]{32}\Z")
ROOT = Path(__file__).resolve().parents[1] / "out/duel-recordings"


def recording_dirs() -> list[Path]:
    if not ROOT.is_dir():
        return []
    return sorted(
        (
            path
            for path in ROOT.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and RECORD_ID.fullmatch(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def details(path: Path) -> dict[str, Any]:
    manifest_path = path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
    size = sum(
        file.stat().st_size
        for file in path.rglob("*")
        if file.is_file() and not file.is_symlink()
    )
    status = manifest.get("status", "legacy_unknown")
    if status == "recording":
        pid = manifest.get("launcher_pid")
        alive = False
        if type(pid) is int and pid > 0:
            try:
                os.kill(pid, 0)
            except OSError:
                pass
            else:
                alive = True
        if not alive:
            status = "interrupted"
    return {
        "record_id": path.name,
        "name": manifest.get("name"),
        "created_at": manifest.get("created_at"),
        "status": status,
        "size_mib": round(size / (1024 * 1024), 1),
        "path": str(path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="show recent recordings")
    listing.add_argument("--limit", type=int, default=10)
    sub.add_parser("latest", help="print the most recent recording path")
    deletion = sub.add_parser("delete", help="delete a recording by ID")
    deletion.add_argument("record_id")
    deletion.add_argument("--yes", action="store_true", help="confirm deletion")
    args = parser.parse_args()

    if args.command == "delete":
        if not RECORD_ID.fullmatch(args.record_id):
            parser.error("record_id must be a 32-character lowercase hexadecimal ID")
        path = ROOT / args.record_id
        if not path.is_dir() or path.is_symlink():
            parser.error(f"recording not found: {args.record_id}")
        item = details(path)
        if not args.yes:
            print(json.dumps(item, ensure_ascii=False, indent=2))
            print("删除请重试并加 --yes")
            return 1
        shutil.rmtree(path)
        print(f"已删除 {args.record_id}")
        return 0

    paths = recording_dirs()
    if args.command == "latest":
        if not paths:
            print("没有录制记录")
            return 1
        print(paths[0].resolve())
        return 0
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    for path in paths[: args.limit]:
        item = details(path)
        print(
            f"{item['record_id']}  {item['status']:<18}  "
            f"{item['size_mib']:>7.1f} MiB  {item['name'] or '-'}"
        )
    if not paths:
        print("没有录制记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
