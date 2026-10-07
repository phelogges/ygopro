"""Database access layer for the ygo-card-db skill.

Provides CardDatabase, a read-only SQLite wrapper for YGOPro-format cards.cdb.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_FILENAME = "cards.cdb"


@dataclass(frozen=True)
class CardData:
    """Raw card data as stored in the datas and texts tables."""

    id: int
    ot: int
    alias: int
    setcode: int
    type: int
    atk: int
    def_field: int
    level: int
    race: int
    attribute: int
    category: int
    name: str
    desc: str


class CardDatabase:
    """Read-only accessor for a YGOPro-format cards.cdb SQLite database.

    Supports use as a context manager:

        with CardDatabase() as db:
            data = db.query_by_id(31809476)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            # Layout: <distribution>/.agents/skills/ygo-card-db/scripts/db.py.
            db_path = Path(__file__).resolve().parents[4] / DB_FILENAME
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> CardDatabase:
        self._get_conn()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                f"{self._db_path.resolve().as_uri()}?mode=ro", uri=True
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def query_by_id(self, card_id: int) -> CardData | None:
        """Look up a single card by its 8-digit password.

        Returns None when no card matches the id.
        """
        conn = self._get_conn()
        row = conn.execute(
            """SELECT d.id, d.ot, d.alias, d.setcode, d.type,
                      d.atk, d.def, d.level, d.race, d.attribute, d.category,
                      t.name, t.desc
               FROM datas d
               JOIN texts t ON d.id = t.id
               WHERE d.id = ?""",
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        return CardData(
            id=row["id"],
            ot=row["ot"],
            alias=row["alias"],
            setcode=row["setcode"],
            type=row["type"],
            atk=row["atk"],
            def_field=row["def"],
            level=row["level"],
            race=row["race"],
            attribute=row["attribute"],
            category=row["category"],
            name=row["name"],
            desc=row["desc"] or "",
        )

    def search_by_keyword(self, keyword: str) -> list[int]:
        """Find card ids whose description text contains a keyword.

        Returns an empty list when no matches are found.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id FROM texts WHERE desc LIKE ?", (f"%{keyword}%",)
        ).fetchall()
        return [row["id"] for row in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
