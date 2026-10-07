"""Build and verify a self-contained macOS Agent client release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
SERVER_PROJECT = ROOT / "agent_server"
REQUIRED_TREES = ("script", "textures", "pics", "sound", "pack")
OPTIONAL_TREES = ("fonts", "icon", "expansions", "resource")
ROOT_FILES = ("cards.cdb", "strings.conf", "lflist.conf")
SKILL_FILES = {
    "ocg-rulebook": ("SKILL.md", "agents/openai.yaml"),
    "ygo-card-db": ("SKILL.md", "agents/openai.yaml"),
}
SKILL_TREES = {
    "ocg-rulebook": ("references",),
    "ygo-card-db": ("scripts",),
}
MANIFEST_PATH = Path(".agents/release-manifest.json")
HASHED_FILES = (
    "ygopro",
    "agent-server",
    "cards.cdb",
    ".agents/config.toml",
    ".agents/skills/ocg-rulebook/SKILL.md",
    ".agents/skills/ygo-card-db/SKILL.md",
)
EXCLUDED_NAMES = {".DS_Store", "__pycache__", ".git", ".env"}


def require_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing regular file: {path}")


def require_tree(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Missing directory: {path}")
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"Release input contains a symlink: {item}")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_database(path: Path) -> None:
    require_file(path)
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise ValueError(f"Invalid card database: {path}: {result}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"datas", "texts"}.issubset(tables):
            raise ValueError(f"Card database lacks datas/texts tables: {path}")


def check_config(path: Path) -> None:
    require_file(path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    model = config.get("model", {})
    if not isinstance(model, dict) or not model.get("api_key_env"):
        raise ValueError(f"Config must name an API-key environment variable: {path}")
    if any(key in model for key in ("api_key", "token", "secret")):
        raise ValueError(f"Config contains a direct secret field: {path}")
    storage = config.get("storage", {})
    if not isinstance(storage, dict) or storage.get("directory") != ".agents/data":
        raise ValueError(f"Release storage must use .agents/data: {path}")


def check_inputs(preset: str) -> None:
    require_file(ROOT / "out/build" / preset / "gframe/ygopro")
    require_file(SERVER_PROJECT / "src/agent_server/__main__.py")
    for name in ("index.html", "app.js", "style.css"):
        require_file(SERVER_PROJECT / "web" / name)
    require_file(SERVER_PROJECT / "uv.lock")
    require_file(ROOT / ".agents/config.example.toml")
    check_config(ROOT / ".agents/config.example.toml")
    for filename in ROOT_FILES:
        require_file(ROOT / filename)
    check_database(ROOT / "cards.cdb")
    for name in REQUIRED_TREES:
        require_tree(ROOT / name)
    for name in OPTIONAL_TREES:
        if (ROOT / name).exists():
            require_tree(ROOT / name)
    for name, files in SKILL_FILES.items():
        skill = ROOT / ".agents/skills" / name
        for filename in files:
            require_file(skill / filename)
        for tree in SKILL_TREES[name]:
            require_tree(skill / tree)
    if (ROOT / ".agents/skills/ygo-card-db/cards.cdb").exists():
        raise ValueError("Remove the obsolete card database inside the skill")


def copy_tree(source: Path, target: Path) -> None:
    require_tree(source)

    def ignored(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in EXCLUDED_NAMES or name.endswith((".pyc", ".log"))
        }

    shutil.copytree(source, target, ignore=ignored)


def build_server(work: Path) -> Path:
    executable = work / "bin/agent-server"
    command = [
        "uv",
        "run",
        "--project",
        str(SERVER_PROJECT),
        "--group",
        "dev",
        "--locked",
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "agent-server",
        "--distpath",
        str(work / "bin"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work / "spec"),
        "--paths",
        str(SERVER_PROJECT / "src"),
        "--paths",
        str(ROOT / "agent_sdk/src"),
        "--add-data",
        f"{SERVER_PROJECT / 'web'}{os.pathsep}web",
        "--collect-all",
        "pydantic_monty",
        "--collect-all",
        "pydantic_ai_harness",
        "--collect-submodules",
        "pydantic_ai",
        "--copy-metadata",
        "genai_prices",
        "--copy-metadata",
        "pydantic_ai_slim",
        str(SERVER_PROJECT / "src/agent_server/__main__.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    require_file(executable)
    return executable


def populate_release(target: Path, preset: str, server_binary: Path) -> None:
    target.mkdir()
    shutil.copy2(ROOT / "out/build" / preset / "gframe/ygopro", target / "ygopro")
    shutil.copy2(server_binary, target / "agent-server")
    for filename in ROOT_FILES:
        shutil.copy2(ROOT / filename, target / filename)
    # Never ship the mutable runtime system.conf from a working tree.
    committed_config = subprocess.run(
        ["git", "show", "HEAD:system.conf"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    (target / "system.conf").write_bytes(committed_config)
    for name in REQUIRED_TREES:
        copy_tree(ROOT / name, target / name)
    for name in OPTIONAL_TREES:
        if (ROOT / name).is_dir():
            copy_tree(ROOT / name, target / name)
    for name in ("deck", "replay", "single"):
        (target / name).mkdir()
    (target / ".agents").mkdir()
    shutil.copy2(ROOT / ".agents/config.example.toml", target / ".agents/config.toml")
    for name, files in SKILL_FILES.items():
        skill_target = target / ".agents/skills" / name
        skill_target.mkdir(parents=True)
        skill_source = ROOT / ".agents/skills" / name
        for filename in files:
            destination = skill_target / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_source / filename, destination)
        for tree in SKILL_TREES[name]:
            copy_tree(skill_source / tree, skill_target / tree)
    manifest = {
        "schema_version": 1,
        "server_version": tomllib.loads(
            (SERVER_PROJECT / "pyproject.toml").read_text()
        )["project"]["version"],
        "platform": "macos",
        "preset": preset,
        "sha256": {name: digest(target / name) for name in HASHED_FILES},
    }
    (target / MANIFEST_PATH).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify_release(target: Path) -> None:
    require_tree(target)
    require_file(target / MANIFEST_PATH)
    for name in (*ROOT_FILES, "system.conf"):
        require_file(target / name)
    if {path.name for path in (target / ".agents").iterdir()} != {
        "config.toml",
        "release-manifest.json",
        "skills",
    }:
        raise ValueError("Release .agents directory contains unexpected files")
    manifest = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("platform") != "macos":
        raise ValueError("Unexpected release manifest")
    expected_hashes = manifest.get("sha256")
    if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(
        HASHED_FILES
    ):
        raise ValueError("Incomplete release manifest hashes")
    for name in HASHED_FILES:
        path = target / name
        require_file(path)
        if digest(path) != expected_hashes[name]:
            raise ValueError(f"Release file hash mismatch: {path}")
    for name in ("ygopro", "agent-server"):
        if not os.access(target / name, os.X_OK):
            raise ValueError(f"Release executable is not executable: {name}")
    for name in REQUIRED_TREES:
        require_tree(target / name)
    for name in ("deck", "replay", "single"):
        require_tree(target / name)
        if any((target / name).iterdir()):
            raise ValueError(f"Release includes personal {name} data")
    for name, files in SKILL_FILES.items():
        skill = target / ".agents/skills" / name
        for filename in files:
            require_file(skill / filename)
        for tree in SKILL_TREES[name]:
            require_tree(skill / tree)
    forbidden = (
        ".agent",
        ".agents/data",
        ".agents/logs",
        ".agents/.env",
        ".agents/skills/ygo-card-db/cards.cdb",
    )
    for name in forbidden:
        if (target / name).exists():
            raise ValueError(f"Forbidden release content: {name}")
    check_config(target / ".agents/config.toml")
    check_database(target / "cards.cdb")


def make_zip(release: Path, archive: Path) -> None:
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
    ) as bundle:
        for path in sorted(release.rglob("*")):
            bundle.write(path, arcname=Path(release.name) / path.relative_to(release))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser(
        "build", help="build a complete directory and versioned zip"
    )
    build_parser.add_argument("--preset", default="MacOS-RelWithDebInfo")
    build_parser.add_argument("--output-dir", type=Path, default=ROOT / "out/release")
    check_parser = subparsers.add_parser(
        "check-inputs", help="check resources before packaging"
    )
    check_parser.add_argument("--preset", default="MacOS-RelWithDebInfo")
    verify_parser = subparsers.add_parser("verify", help="validate a release directory")
    verify_parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify_release(args.directory.resolve())
            print(f"Verified: {args.directory}")
            return 0
        if args.command == "check-inputs":
            check_inputs(args.preset)
            print("Release inputs verified")
            return 0
        if not args.preset.startswith("MacOS-"):
            raise ValueError("The current release builder supports macOS presets only")
        subprocess.run(["cmake", "--preset", args.preset], cwd=ROOT, check=True)
        subprocess.run(
            ["cmake", "--build", "--preset", args.preset], cwd=ROOT, check=True
        )
        check_inputs(args.preset)
        version = tomllib.loads((SERVER_PROJECT / "pyproject.toml").read_text())[
            "project"
        ]["version"]
        name = f"ygopro-agent-macos-{version}"
        output = args.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        release = output / name
        archive = output / f"{name}.zip"
        if release.exists() or archive.exists():
            raise ValueError(f"Release already exists: {release} or {archive}")
        with tempfile.TemporaryDirectory(prefix="agent-release-", dir=output) as temp:
            temporary = Path(temp)
            server_binary = build_server(temporary)
            staged_release = temporary / name
            populate_release(staged_release, args.preset, server_binary)
            verify_release(staged_release)
            staged_archive = temporary / archive.name
            make_zip(staged_release, staged_archive)
            staged_release.rename(release)
            staged_archive.rename(archive)
        print(f"Release directory: {release}")
        print(f"Release archive: {archive}")
        return 0
    except (
        OSError,
        ValueError,
        sqlite3.Error,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"agent-release: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
