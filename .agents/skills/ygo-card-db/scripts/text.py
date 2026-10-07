"""Card text parsing logic for the ygo-card-db skill.

Implements the extraction rules defined in cards.md:

1. Old vs. new: 「①：」 marker presence decides the split.
2. Non-pendulum new cards: split at 「①：」 → non_effect_text / effect_text.
3. Normal non-pendulum monsters: all fields None (flavour text is not
   gameplay-relevant).
4. Pendulum cards: two independent text sets (P effect + monster effect),
   each split the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_MARKER = "①："
_P_SCALE_RE = re.compile(r"←(\d+)\s*【灵摆】\s*(\d+)→")
_MONSTER_EFFECT_SEP = "【怪兽效果】"
_MONSTER_DESC_SEP = "【怪兽描述】"


@dataclass
class CardText:
    """The five text fields that describe a card's gameplay-relevant text.

    For any given card, only the subset that applies (old vs. new,
    pendulum vs. non-pendulum, normal vs. effect) will be populated.
    """

    non_effect_text: str | None = None
    effect_text: str | None = None
    card_text: str | None = None
    p_effect_text: str | None = None
    p_non_effect_text: str | None = None


class CardTextParser:
    """Parses raw card description text into structured CardText objects.

    Follows rules defined in cards.md to split old/new style text and
    handle pendulum cards' dual-text format.
    """

    @staticmethod
    def _split_new_text(text: str) -> tuple[str | None, str | None]:
        """Split new-style text at the first 「①：」 marker.

        Returns (non_effect_text, effect_text). None means that part
        is absent or empty.
        """
        text = text.strip()
        if not text:
            return None, None
        idx = text.find(_MARKER)
        if idx == -1:
            return None, None
        non_effect = text[:idx].strip()
        effect = text[idx:].strip()
        return (non_effect or None, effect or None)

    @staticmethod
    def extract_pendulum_scales(desc: str) -> tuple[int | None, int | None]:
        """Extract pendulum scales from 「←N 【灵摆】 N→」 header."""
        m = _P_SCALE_RE.search(desc)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    def parse(
        self, desc: str, card_type: int, is_normal: bool = False,
    ) -> CardText:
        """Parse card description text according to rules in cards.md."""
        from scripts.types import CardType  # noqa: PLC0415

        desc = desc.strip()
        is_pendulum = bool(card_type & CardType.TYPE_PENDULUM)
        is_normal_monster = is_normal and bool(card_type & CardType.TYPE_MONSTER)

        if is_normal_monster and not is_pendulum:
            return CardText()

        if not is_pendulum:
            if _MARKER not in desc:
                return CardText(card_text=desc or None)
            non_effect, effect = self._split_new_text(desc)
            return CardText(non_effect_text=non_effect, effect_text=effect)

        # Pendulum card: parse P text and monster text separately.
        if _MONSTER_DESC_SEP in desc:
            p_part, _ = desc.split(_MONSTER_DESC_SEP, 1)
            m_part = ""
        elif _MONSTER_EFFECT_SEP in desc:
            p_part, m_part = desc.split(_MONSTER_EFFECT_SEP, 1)
        else:
            p_part = desc
            m_part = ""

        p_part = _P_SCALE_RE.sub("", p_part, count=1).strip()

        if _MARKER in p_part:
            p_ne, p_e = self._split_new_text(p_part)
        else:
            p_ne = None
            p_e = p_part or None

        m_part = m_part.strip()
        if is_normal:
            m_ne: str | None = None
            m_e: str | None = None
        elif _MARKER in m_part:
            m_ne, m_e = self._split_new_text(m_part)
        else:
            m_ne = None
            m_e = m_part or None

        return CardText(
            non_effect_text=m_ne,
            effect_text=m_e,
            p_non_effect_text=p_ne,
            p_effect_text=p_e,
        )
