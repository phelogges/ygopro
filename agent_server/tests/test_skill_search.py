"""Card-name and description search share one local database but distinct tools."""

from pathlib import Path

import pytest

from agent_server.codex_mcp_bridge import TOOL_SCHEMAS
from agent_server.skills import SkillResources

ROOT = Path(__file__).resolve().parents[2]


def test_card_name_search_exact_first_duplicates_and_pagination() -> None:
    skills = SkillResources(ROOT)
    exact = skills.search_card_names("青眼白龙", limit=2)
    assert exact["total"] > 2
    assert exact["matches"] == [
        {"card_id": 89631139, "name": "青眼白龙"},
        {"card_id": 89631140, "name": "青眼白龙"},
    ]
    assert (
        skills.search_card_names("青眼白龙", limit=1, offset=1)["matches"] == exact["matches"][1:]
    )
    assert skills.search_card_names("地狱亡灵")["matches"] == [
        {"card_id": 40575313, "name": "地狱亡灵"}
    ]
    assert skills.search_card_names("%") == {
        "keyword": "%",
        "matches": [{"card_id": 6859683, "name": "成功确率0%"}],
        "total": 1,
    }


def test_description_search_still_returns_ids_and_both_mcp_names_exist() -> None:
    skills = SkillResources(ROOT)
    descriptions = skills.search_card_descriptions("青眼", limit=2)
    assert descriptions["total"] >= 2
    assert len(descriptions["ids"]) == 2
    assert "matches" not in descriptions
    assert "search_card_descriptions" in TOOL_SCHEMAS
    assert "search_card_names" in TOOL_SCHEMAS
    assert "search_cards" not in TOOL_SCHEMAS


@pytest.mark.parametrize("keyword,limit,offset", [("", 30, 0), ("a", 0, 0), ("a", 30, -1)])
def test_card_name_search_rejects_invalid_page(keyword: str, limit: int, offset: int) -> None:
    with pytest.raises(ValueError):
        SkillResources(ROOT).search_card_names(keyword, limit=limit, offset=offset)
