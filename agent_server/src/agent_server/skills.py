"""Release-local, read-only rulebook and card database tools."""

import hashlib
import importlib
import sys
from pathlib import Path
from typing import Any

RULE_SECTIONS = frozenset(
    {
        "overview",
        "field",
        "cards",
        "effects",
        "non-effect-text",
        "game-progression",
        "tournament",
    }
)


class SkillResources:
    def __init__(self, release_root: Path) -> None:
        self.root = release_root.resolve()
        self.skill_root = self.root / ".agents" / "skills"
        self.card_skill = self.skill_root / "ygo-card-db"
        self.rule_skill = self.skill_root / "ocg-rulebook"
        self.database = self.root / "cards.cdb"
        for directory in (self.skill_root, self.card_skill, self.rule_skill):
            if not directory.resolve().is_relative_to(self.root):
                raise ValueError(f"skill directory escapes the release root: {directory}")
        for required in (
            self.card_skill / "SKILL.md",
            self.card_skill / "scripts" / "query.py",
            self.rule_skill / "SKILL.md",
            self.database,
        ):
            if not required.resolve().is_relative_to(self.root):
                raise ValueError(f"release resource escapes the release root: {required}")
            if not required.is_file():
                raise FileNotFoundError(f"required release resource is missing: {required}")
        digest = hashlib.sha256()
        with self.database.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        self.database_sha256 = digest.hexdigest()
        self._card_query_type: type[Any] | None = None

    def _card_query(self) -> Any:
        if self._card_query_type is None:
            skill_path = str(self.card_skill)
            if skill_path not in sys.path:
                sys.path.insert(0, skill_path)
            module = importlib.import_module("scripts.query")
            if module.__file__ is None:
                raise RuntimeError("card skill module has no source file")
            loaded = Path(module.__file__).resolve()
            if not loaded.is_relative_to(self.card_skill.resolve()):
                raise RuntimeError("card skill module resolved outside the release-local skill")
            query_type = getattr(module, "CardQuery", None)
            if query_type is None:
                raise RuntimeError("card skill has no CardQuery")
            self._card_query_type = query_type
        query_type = self._card_query_type
        assert query_type is not None
        return query_type()

    def card_by_id(self, card_id: int) -> dict[str, Any]:
        if not 1 <= card_id <= 0xFFFFFFFF:
            raise ValueError("card_id outside supported range")
        query = self._card_query()
        try:
            return query.query_by_id(card_id)
        finally:
            query.close()

    def cards_by_ids(self, card_ids: list[int]) -> list[dict[str, Any]]:
        """Read several public cards through one local card-database handle."""
        if any(type(card_id) is not int or not 1 <= card_id <= 0xFFFFFFFF for card_id in card_ids):
            raise ValueError("card_ids contains an invalid card ID")
        if len(set(card_ids)) != len(card_ids):
            raise ValueError("card_ids must be distinct")
        query = self._card_query()
        try:
            return query.query_by_ids(card_ids)
        finally:
            query.close()

    def search_card_descriptions(
        self, keyword: str, *, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        if not keyword or len(keyword) > 120:
            raise ValueError("keyword must contain 1 to 120 characters")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid card search page")
        query = self._card_query()
        try:
            ids: list[int] = query.search_by_keyword(keyword)
        finally:
            query.close()
        return {"keyword": keyword, "ids": ids[offset : offset + limit], "total": len(ids)}

    def search_card_names(
        self, keyword: str, *, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        if not keyword or len(keyword) > 120:
            raise ValueError("keyword must contain 1 to 120 characters")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid card search page")
        query = self._card_query()
        try:
            matches: list[dict[str, int | str]] = query.search_names(keyword)
        finally:
            query.close()
        return {
            "keyword": keyword,
            "matches": matches[offset : offset + limit],
            "total": len(matches),
        }

    def rulebook_index(self) -> str:
        return (self.rule_skill / "SKILL.md").read_text(encoding="utf-8")

    def rulebook_section(self, section: str) -> str:
        if section not in RULE_SECTIONS:
            raise ValueError("unknown rulebook section")
        path = self.rule_skill / "references" / f"{section}.md"
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("rulebook reference escapes the release root")
        return path.read_text(encoding="utf-8")
