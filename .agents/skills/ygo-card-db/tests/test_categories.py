"""Keep cards.cdb category decoding aligned with the client deck filter."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SKILL_ROOT))

from scripts.query import CardQuery  # noqa: E402
from scripts.types import Category  # noqa: E402


class CategoryTests(unittest.TestCase):
    def test_category_labels_match_client_strings(self) -> None:
        labels = {}
        for line in (
            (PROJECT_ROOT / "strings.conf").read_text(encoding="utf-8").splitlines()
        ):
            match = re.match(r"!system (11\d\d)\s+(.+?)\s*$", line)
            if match and 1100 <= int(match.group(1)) <= 1131:
                labels[int(match.group(1))] = match.group(2).strip()
        self.assertEqual(len(labels), 32)
        self.assertEqual(
            [(int(category), category.text) for category in Category],
            [(1 << index, labels[1100 + index]) for index in range(32)],
        )

    def test_original_sinful_spoils_categories(self) -> None:
        query = CardQuery()
        try:
            card = query.query_by_id(89023486)
        finally:
            query.close()
        self.assertEqual(
            card["effect_categories"],
            ["返回卡组", "卡组检索", "卡片回收", "特殊召唤"],
        )


if __name__ == "__main__":
    unittest.main()
