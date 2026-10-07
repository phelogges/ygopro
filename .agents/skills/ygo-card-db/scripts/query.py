"""Card query interface for the ygo-card-db skill.

Provides CardDecoder (binary field → natural language) and CardQuery
(main entry point for id/keyword lookups).

Usage as CLI:
    cd <skill-root> && uv run python -m scripts.query 31809476 56725612
    cd <skill-root> && uv run python -m scripts.query search "特殊召唤"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Ensure the skill root is on sys.path so 'from scripts.xxx' imports work.
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from scripts.db import CardData, CardDatabase  # noqa: E402
from scripts.text import CardTextParser  # noqa: E402
from scripts.types import (  # noqa: E402
    ARCHETYPES_BY_ROOT,
    CARD_ARTWORK_VERSIONS_OFFSET,
    LINK_MARKER_DISPLAY,
    LINK_MARKER_ORDER,
    UNKNOWN_ATK_DEF,
    ArchetypeOutput,
    Attribute,
    CardAvailability,
    CardType,
    Category,
    Race,
)


# ---------------------------------------------------------------------------
# CardDecoder
# ---------------------------------------------------------------------------

class CardDecoder:
    """Decodes raw binary fields from datas table into natural-language values.

    Args:
        archetype_output: Controls language for archetype name output.
    """

    def __init__(
        self, archetype_output: ArchetypeOutput = ArchetypeOutput.CHINESE_ONLY,
    ) -> None:
        self._archetype_output = archetype_output

    def decode_type(self, type_val: int) -> list[str]:
        return [t.text for t in CardType if type_val & t]

    def decode_race(self, race_val: int) -> str | None:
        for flag in Race:
            if race_val & flag:
                return flag.text
        return None

    def decode_attribute(self, attr_val: int) -> str | None:
        for flag in Attribute:
            if attr_val & flag:
                return flag.text
        return None

    def decode_level_rank_link(
        self, level_val: int, type_val: int,
    ) -> tuple[int | None, int | None, int | None]:
        """Return (level, rank, link). Exactly one non-None for monsters."""
        if not (type_val & CardType.TYPE_MONSTER):
            return None, None, None
        raw = level_val & 0xFF
        if raw == 0:
            return None, None, None
        if type_val & CardType.TYPE_XYZ:
            return None, raw, None
        if type_val & CardType.TYPE_LINK:
            return None, None, raw
        return raw, None, None

    def decode_pendulum_scales(
        self, level_val: int, type_val: int,
    ) -> dict[str, int] | None:
        """Return {"左": left, "右": right} or None for non-pendulum."""
        if not (type_val & CardType.TYPE_PENDULUM):
            return None
        left = (level_val >> 24) & 0xFF
        right = (level_val >> 16) & 0xFF
        return {"左": left, "右": right}

    def decode_link_markers(
        self, def_val: int, type_val: int,
    ) -> list[str] | None:
        """Return ordered link marker direction names, or None."""
        if not (type_val & CardType.TYPE_LINK):
            return None
        return [
            LINK_MARKER_DISPLAY[flag]
            for flag in LINK_MARKER_ORDER
            if def_val & flag
        ]

    def decode_archetypes(self, setcode: int) -> list[str]:
        result: list[str] = []
        remaining = setcode
        while remaining:
            code = remaining & 0xFFFF
            remaining >>= 16
            if code == 0:
                continue
            root = code & 0x0FFF
            sub = code >> 12
            for target_code, archetype in ARCHETYPES_BY_ROOT.get(root, ()):
                if (sub & (target_code >> 12)) == (target_code >> 12):
                    if self._archetype_output == ArchetypeOutput.BOTH:
                        result.append(f"{archetype.zh}（{archetype.ja}）")
                    elif self._archetype_output == ArchetypeOutput.CHINESE_ONLY:
                        result.append(archetype.zh)
                    else:
                        result.append(archetype.ja)
        return result

    def decode_availability(self, ot: int) -> list[str]:
        return [avail.text for avail in CardAvailability if ot & avail]

    def decode_categories(self, cat_val: int) -> list[str]:
        return [cat.text for cat in Category if cat_val & cat]

    def decode_atk(self, atk: int, type_val: int) -> int | None:
        if not (type_val & CardType.TYPE_MONSTER):
            return None
        return self._format_atk_def(atk)

    def decode_def(self, def_val: int, type_val: int) -> int | None:
        if not (type_val & CardType.TYPE_MONSTER):
            return None
        if type_val & CardType.TYPE_LINK:
            return None
        return self._format_atk_def(def_val)

    @staticmethod
    def _format_atk_def(val: int) -> int | None:
        if val == UNKNOWN_ATK_DEF:
            return UNKNOWN_ATK_DEF
        if val < 0:
            return None
        return val

    @staticmethod
    def decode_alias(alias: int, card_id: int) -> int | None:
        """Decode alias. Returns alias id or None.

        Artwork variants (id gap < OFFSET) return None.
        Rulebook name twins return the alias card id.
        """
        if alias == 0:
            return None
        if abs(alias - card_id) < CARD_ARTWORK_VERSIONS_OFFSET:
            return None
        return alias


# ---------------------------------------------------------------------------
# CardQuery
# ---------------------------------------------------------------------------

_EMPTY_RESULT: dict[str, Any] = {
    "id": 0,
    "name": None,
    "card_type": [],
    "race": None,
    "attribute": None,
    "atk": None,
    "def": None,
    "level": None,
    "rank": None,
    "link": None,
    "pendulum_scales": None,
    "link_markers": None,
    "archetypes": [],
    "effect_categories": [],
    "non_effect_text": None,
    "effect_text": None,
    "card_text": None,
    "p_effect_text": None,
    "p_non_effect_text": None,
}


class CardQuery:
    """Main query interface for the YGO card database.

    Args:
        db: Optional CardDatabase instance. Created on-demand when omitted.
        include_availability: If True, include the availability field.
        archetype_output: Archetype name language mode.
    """

    def __init__(
        self,
        db: CardDatabase | None = None,
        *,
        include_availability: bool = False,
        archetype_output: ArchetypeOutput = ArchetypeOutput.CHINESE_ONLY,
    ) -> None:
        self._db = db or CardDatabase()
        self._own_db = db is None
        self._include_availability = include_availability
        self._decoder = CardDecoder(archetype_output=archetype_output)
        self._text_parser = CardTextParser()

    def query_by_id(self, card_id: int) -> dict[str, Any]:
        """Look up a single card and return structured dict (JSON-friendly)."""
        data = self._db.query_by_id(card_id)
        if data is None:
            result = dict(_EMPTY_RESULT)
            result["id"] = card_id
            if self._include_availability:
                result["availability"] = []
            return result
        return self._build_result(data)

    def query_by_ids(self, card_ids: list[int]) -> list[dict[str, Any]]:
        """Look up multiple cards."""
        return [self.query_by_id(cid) for cid in card_ids]

    def search_by_keyword(self, keyword: str) -> list[int]:
        """Find card ids whose description text contains a keyword."""
        return self._db.search_by_keyword(keyword)

    def close(self) -> None:
        if self._own_db:
            self._db.close()

    def _build_result(self, data: CardData) -> dict[str, Any]:
        is_normal = bool(data.type & CardType.TYPE_NORMAL)
        card_text = self._text_parser.parse(
            data.desc, data.type, is_normal=is_normal,
        )
        level, rank, link = self._decoder.decode_level_rank_link(
            data.level, data.type,
        )
        result: dict[str, Any] = {
            "id": data.id,
            "name": data.name,
            "alias": self._decoder.decode_alias(data.alias, data.id),
            "card_type": self._decoder.decode_type(data.type),
            "race": self._decoder.decode_race(data.race),
            "attribute": self._decoder.decode_attribute(data.attribute),
            "atk": self._decoder.decode_atk(data.atk, data.type),
            "def": self._decoder.decode_def(data.def_field, data.type),
            "level": level,
            "rank": rank,
            "link": link,
            "pendulum_scales": self._decoder.decode_pendulum_scales(
                data.level, data.type,
            ),
            "link_markers": self._decoder.decode_link_markers(
                data.def_field, data.type,
            ),
            "archetypes": self._decoder.decode_archetypes(data.setcode),
            "effect_categories": self._decoder.decode_categories(data.category),
            "non_effect_text": card_text.non_effect_text,
            "effect_text": card_text.effect_text,
            "card_text": card_text.card_text,
            "p_effect_text": card_text.p_effect_text,
            "p_non_effect_text": card_text.p_non_effect_text,
        }
        if self._include_availability:
            result["availability"] = self._decoder.decode_availability(data.ot)
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with subcommands for query and search.

    Backward compatibility: if the first positional argument is a plain
    card id (all digits), it is treated as ``query <id>``.
    """
    parser = argparse.ArgumentParser(
        prog="query.py",
        description="游戏王卡片数据库查询工具。两种模式：(1) 根据卡片8位密码精确查询卡片详细信息；(2) 根据关键字搜索卡片描述，返回匹配的卡片id列表。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用示例:\n"
            "  query.py query 31809476         精确查询单张卡片\n"
            "  query.py query 31809476 30064423 精确查询多张卡片\n"
            "  query.py query --include-availability 31809476  查询并附带登场地区\n"
            "  query.py query --archetype-output 0 31809476     系列名双语输出\n"
            "  query.py search 青眼         搜索描述中含\"青眼\"的卡片id\n"
            "\n"
            "兼容旧版: query.py 31809476  等价于  query.py query 31809476"
        ),
    )
    subs = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- query subcommand ---
    q = subs.add_parser(
        "query",
        help="根据卡片8位密码精确查询卡片信息",
        description="根据卡片8位密码(id)从数据库中检索卡片，输出包含类型、种族、属性、攻守、效果文本等的结构化JSON。",
    )
    q.add_argument(
        "ids", metavar="ID", nargs="+", type=int,
        help="卡片8位密码（可同时指定多张，空格分隔）",
    )
    q.add_argument(
        "--include-availability", action="store_true",
        help="在输出中附带 availability 字段，显示登场地区（OCG / TCG / 简体中文）",
    )
    q.add_argument(
        "--archetype-output", type=int, choices=[0, 1, 2], default=1,
        help="系列名输出语言: 0=中日双语  1=仅中文（默认）  2=仅日文",
    )

    # --- search subcommand ---
    s = subs.add_parser(
        "search",
        help="根据关键字搜索卡片描述，返回匹配的卡片id列表",
        description="在卡片描述文本中搜索关键字，返回匹配的卡片id列表，用于发现效果相关卡片。",
    )
    s.add_argument(
        "keyword", metavar="KEYWORD",
        help="在卡片描述文本中搜索的关键字，如 特殊召唤、破坏、除外 等",
    )

    return parser


def main() -> None:
    """Parse CLI arguments and dispatch to query or search."""
    # Backward compat: plain card-id positional → automatically treat as query.
    if len(sys.argv) > 1 and sys.argv[1] not in ("query", "search", "-h", "--help"):
        sys.argv.insert(1, "query")

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "query":
        ao = ArchetypeOutput(args.archetype_output)
        cq = CardQuery(
            include_availability=args.include_availability,
            archetype_output=ao,
        )
        try:
            result = (
                cq.query_by_id(args.ids[0])
                if len(args.ids) == 1
                else cq.query_by_ids(args.ids)
            )
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            sys.stdout.flush()
        finally:
            cq.close()

    elif args.command == "search":
        cq = CardQuery()
        try:
            ids = cq.search_by_keyword(args.keyword)
            json.dump(
                {"keyword": args.keyword, "ids": ids},
                sys.stdout, ensure_ascii=False, indent=2,
            )
            sys.stdout.write("\n")
            sys.stdout.flush()
        finally:
            cq.close()


if __name__ == "__main__":
    main()
