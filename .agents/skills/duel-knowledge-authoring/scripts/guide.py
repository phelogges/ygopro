"""Create and check human-authored duel knowledge templates."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "cards.cdb"
ZONE_NAMES = {"main": "主卡组", "extra": "额外卡组", "side": "备牌"}
OWN_SECTIONS = (
    "单卡表",
    "整体获胜思路",
    "关键资源与限制",
    "先攻计划",
    "后攻与返场计划",
    "受阻后的调整",
    "对手回合的交互思路",
    "Match 与换备牌",
    "依据与待验证项",
)
POPULAR_SECTIONS = (
    "热门单卡表",
    "辨识线索与构筑分支",
    "常见起动与终场",
    "持续资源与关键转换点",
    "常见补点与受阻后的路线",
    "先攻与后攻威胁",
    "已知应对经验",
    "Match 与备牌目标",
    "依据与待验证项",
)


def card_id(value: str) -> int:
    if not value.isdecimal() or not 1 <= int(value) <= 0xFFFFFFFF:
        raise ValueError(f"无效卡片 ID：{value}")
    return int(value)


def deck_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT / "deck") or path.suffix.lower() != ".ydk":
        raise ValueError("本方构筑必须是项目 deck/ 下的 .ydk 文件")
    if not path.is_file():
        raise ValueError(f"卡组文件不存在：{path}")
    return path


def read_deck(path: Path) -> dict[str, Counter[int]]:
    zones: dict[str, Counter[int]] = {zone: Counter() for zone in ZONE_NAMES}
    current: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if line == "#main":
            current = "main"
        elif line == "#extra":
            current = "extra"
        elif line == "!side":
            current = "side"
        elif not line or line.startswith("#"):
            continue
        elif current is None:
            raise ValueError(f"{path}:{number}: 卡片 ID 位于区域标记之前")
        else:
            zones[current][card_id(line)] += 1
    if not zones["main"]:
        raise ValueError(f"{path}: 主卡组为空或缺少 #main")
    return zones


def card_names(ids: set[int]) -> dict[int, str]:
    if not DATABASE.is_file():
        raise ValueError(f"缺少本地卡片数据库：{DATABASE}")
    if not ids:
        return {}
    numbers = sorted(ids)
    with sqlite3.connect(DATABASE) as connection:
        names: dict[int, str] = {}
        for offset in range(0, len(numbers), 500):
            batch = numbers[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            names.update(
                connection.execute(
                    f"SELECT id, name FROM texts WHERE id IN ({placeholders})", batch
                )
            )
    missing = sorted(ids - names.keys())
    if missing:
        raise ValueError("卡库中找不到这些 ID：" + ", ".join(map(str, missing)))
    return names


def slug(value: str) -> str:
    result = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._-")
    if not result or result in {".", ".."}:
        raise ValueError("目录名不能为空")
    return result


def write_new(template: str, replacements: dict[str, str], output: Path) -> None:
    source = (SKILL / "assets" / template).read_text(encoding="utf-8")
    for key, value in replacements.items():
        source = source.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[^}]+\}\}", source):
        raise ValueError("模板含未替换的变量")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(source)
    print(output)


def new_own(args: argparse.Namespace) -> None:
    path = deck_path(args.ydk)
    relative = path.relative_to(ROOT)
    name = slug("_".join(path.relative_to(ROOT / "deck").with_suffix("").parts))
    zones = read_deck(path)
    rows = [
        f"| {ZONE_NAMES[zone]} | {number:08d} | {count} | 待填写 |"
        for zone, cards in zones.items()
        for number, count in cards.items()
    ]
    output = args.output or ROOT / "docs" / "draft" / "deck-guides" / name / "input.md"
    write_new(
        "own.md",
        {"title": name, "deck_path": relative.as_posix(), "card_rows": "\n".join(rows)},
        output,
    )


def new_popular(args: argparse.Namespace) -> None:
    numbers = [card_id(value) for value in args.ids]
    if len(set(numbers)) != len(numbers):
        raise ValueError("热门卡清单有重复 ID")
    card_names(set(numbers))
    name = slug(args.slug or args.series)
    rows = [f"| {number:08d} | 待填写 |" for number in numbers]
    output = (
        args.output or ROOT / "docs" / "draft" / "popular-series" / name / "input.md"
    )
    write_new(
        "popular.md",
        {
            "title": args.series,
            "series": args.series,
            "slug": name,
            "card_rows": "\n".join(rows),
        },
        output,
    )


def sections(content: str) -> dict[str, str]:
    found: dict[str, str] = {}
    title: str | None = None
    lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if title is not None:
                found[title] = "\n".join(lines).strip()
            title, lines = line[3:].strip(), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        found[title] = "\n".join(lines).strip()
    return found


def metadata(content: str) -> dict[str, str]:
    return dict(re.findall(r"^- ([^：\n]+)：([^\n]*)$", content, re.MULTILINE))


def table_rows(body: str, headers: tuple[str, ...]) -> list[list[str]]:
    lines = [line for line in body.splitlines() if line.startswith("|")]
    if len(lines) < 2:
        raise ValueError("单卡表缺少表头或数据行")
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if rows[0] != list(headers):
        raise ValueError("单卡表表头与模板不一致")
    if len(rows[1]) != len(headers) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]
    ):
        raise ValueError("单卡表缺少 Markdown 分隔行")
    if any(len(row) != len(headers) for row in rows[2:]):
        raise ValueError("单卡表有列数不符的行")
    return rows[2:]


def check(path: Path) -> int:
    content = path.read_text(encoding="utf-8")
    meta, parts = metadata(content), sections(content)
    errors: list[str] = []
    mode = meta.get("类型")
    required = OWN_SECTIONS if mode == "本方构筑" else POPULAR_SECTIONS
    if mode not in {"本方构筑", "热门系列"}:
        errors.append("类型必须是本方构筑或热门系列")
    for field in ("环境", "禁限卡表生效日期", "最后复核日期"):
        if field not in meta:
            errors.append(f"缺少元信息：{field}")
    if meta.get("环境") not in {"OCG", "TCG"}:
        errors.append("环境必须明确填写 OCG 或 TCG")
    for field in ("禁限卡表生效日期", "最后复核日期"):
        try:
            date.fromisoformat(meta.get(field, ""))
        except ValueError:
            errors.append(f"{field} 必须是有效的 YYYY-MM-DD 日期")
    for title in required:
        body = parts.get(title, "")
        if not body:
            errors.append(f"缺少或未填写栏目：{title}")
        elif title not in {"单卡表", "热门单卡表"} and "待填写" in body:
            errors.append(f"栏目尚未填写：{title}（可明确写待验证及原因）")

    try:
        if mode == "本方构筑":
            deck = read_deck(deck_path(meta.get("构筑路径", "")))
            actual: dict[str, Counter[int]] = {zone: Counter() for zone in ZONE_NAMES}
            reverse = {name: zone for zone, name in ZONE_NAMES.items()}
            seen: set[tuple[str, int]] = set()
            for row in table_rows(
                parts.get("单卡表", ""), ("区域", "ID", "张数", "基本用法")
            ):
                zone_name, raw_id, raw_count, usage = row
                if zone_name not in reverse:
                    errors.append(f"单卡表区域无效：{zone_name}")
                    continue
                number = card_id(raw_id)
                if (zone_name, number) in seen:
                    errors.append(f"单卡表有重复 ID：{zone_name} {raw_id}")
                seen.add((zone_name, number))
                if not raw_count.isdecimal() or int(raw_count) < 1:
                    errors.append(f"{raw_id} 的张数无效：{raw_count}")
                    continue
                actual[reverse[zone_name]][number] += int(raw_count)
                if "待填写" in usage or not usage:
                    errors.append(f"{raw_id} 尚未填写基本用法")
            if actual != deck:
                errors.append("单卡表的区域、ID 或张数与 .ydk 不一致")
            card_names({number for cards in actual.values() for number in cards})
        elif mode == "热门系列":
            if not meta.get("系列名称") or not meta.get("目录名"):
                errors.append("缺少系列名称或目录名")
            numbers: list[int] = []
            for raw_id, usage in table_rows(
                parts.get("热门单卡表", ""), ("ID", "基本用法")
            ):
                number = card_id(raw_id)
                numbers.append(number)
                if "待填写" in usage or not usage:
                    errors.append(f"{raw_id} 尚未填写基本用法")
            if not numbers:
                errors.append("热门单卡表为空")
            if len(numbers) != len(set(numbers)):
                errors.append("热门单卡表有重复 ID")
            card_names(set(numbers))
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        for error in errors:
            print(f"- {error}")
        print(
            f"检查未通过：{len(errors)} 项；修正或在填写稿中明确标注待验证后继续追问。"
        )
        return 1
    print("结构与卡片清单检查通过；策略内容、规则解释和禁限合法性仍需人工审查。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    own = commands.add_parser("new-own", help="从 deck/ 下的 YDK 生成本方填写稿")
    own.add_argument("--ydk", required=True)
    own.add_argument("--output", type=Path)
    popular = commands.add_parser(
        "new-popular", help="从用户提供的热门单卡 ID 生成系列填写稿"
    )
    popular.add_argument("--series", required=True)
    popular.add_argument("--slug", help="正式指南目录名；默认由系列名称生成")
    popular.add_argument("--ids", nargs="+", required=True)
    popular.add_argument("--output", type=Path)
    validation = commands.add_parser("check", help="检查填写稿的确定性结构和卡片清单")
    validation.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "new-own":
            new_own(args)
        elif args.command == "new-popular":
            new_popular(args)
        else:
            return check(args.input)
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
