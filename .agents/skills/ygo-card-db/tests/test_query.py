"""Validation tests for the refactored ygo-card-db query module.

Exercises every test case listed in references/cards.md and asserts
basic invariants on the returned JSON structure.

Ported from the original tests/ to use the new OOP CardQuery API.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_ROOT))

from scripts.query import CardQuery  # noqa: E402
from scripts.types import ArchetypeOutput  # noqa: E402

# ---------------------------------------------------------------------------
# All test-case IDs from cards.md
# ---------------------------------------------------------------------------

NEW_SPELL_TRAP = [
    (31809476, "速攻魔法"),
    (56725612, "场地魔法"),
    (81143465, "装备魔法"),
    (32665564, "永续魔法"),
    (93871599, "通常魔法"),
    (41085464, "仪式魔法"),
    (5125629,  "通常陷阱"),
    (92936364, "永续陷阱"),
    (41420027, "反击陷阱"),
]

NEW_MONSTERS = [
    (5559570,  "同调"),
    (65961304, "同调调整"),
    (48654267, "同调灵摆"),
    (37818794, "融合"),
    (66532962, "融合调整"),
    # 71808988 not in DB,
    (5148778,  "融合灵摆"),
    (90091224, "XYZ"),
    (30095833, "XYZ灵摆"),
    (13332685, "仪式"),
    (92487128, "仪式灵摆"),
    (65037172, "仪式调整"),
    (42932862, "仪式反转"),
    (33325951, "仪式灵魂"),
    (30064423, "连接"),
    (42382265, "效果灵摆"),
    (57448410, "通常灵摆"),
    (11012154, "通常调整"),
    (3405259,  "同盟"),
    (32181268, "灵魂"),
    (30079770, "二重"),
    (42386471, "卡通"),
    (22865492, "效果(永续陷阱)"),
    (90241276, "效果(永续魔法)"),
    (77411244, "效果(装备魔法)"),
    (74294676, "XYZ"),
    (91284003, "永续陷阱/效果怪兽(陷阱怪兽)"),
    (91842653, "卡通"),
]

OLD_SPELL_TRAP = [
    (62437430, "永续魔法"),
    (70222318, "场地魔法"),
    (49398568, "速攻魔法"),
    (48576971, "装备魔法"),
    (242146,   "通常魔法"),
    (43694075, "仪式魔法"),
    (34707034, "通常陷阱"),
    (87313164, "反击陷阱"),
]

OLD_MONSTERS = [
    (22377815, "二重"),
    (23689697, "效果"),
    (95526884, "同调"),
    (67556500, "同调调整"),
    (90957527, "融合"),
    (91782219, "仪式"),
    (47415292, "同盟"),
    (77084837, "灵魂"),
    (80549379, "效果(装备魔法)"),
]

# ---------------------------------------------------------------------------
_passed = 0
_failed = 0


def ok(cid: int, label: str, msg: str = "") -> None:
    global _passed
    _passed += 1
    text = f"  OK  [{cid}] {label}"
    if msg:
        text += f"  — {msg}"
    print(text)


def fail(cid: int, label: str, detail: str) -> None:
    global _failed
    _failed += 1
    print(f"  FAIL [{cid}] {label}  — {detail}")


def run_all() -> int:
    cq = CardQuery(archetype_output=ArchetypeOutput.CHINESE_ONLY)

    for cid, label in NEW_SPELL_TRAP:
        d = cq.query_by_id(cid)
        check_not_null(cid, label, d, "name")
        check_non_empty_list(cid, label, d, "card_type")
        check_new_style(cid, label, d)
        check_non_monster(cid, label, d)

    for cid, label in NEW_MONSTERS:
        d = cq.query_by_id(cid)
        check_not_null(cid, label, d, "name")
        check_non_empty_list(cid, label, d, "card_type")
        check_is_monster(cid, label, d)
        check_new_style(cid, label, d)

        if any(kw in label for kw in ("灵摆",)):
            check_pendulum(cid, label, d)
        if "通常" in label and "调整" in label and "灵摆" not in label:
            check_normal_texts(cid, label, d)
        if "连接" in label:
            check_link(cid, label, d)
        if "XYZ" in label:
            check_xyz(cid, label, d)

    for cid, label in OLD_SPELL_TRAP:
        d = cq.query_by_id(cid)
        check_not_null(cid, label, d, "name")
        check_non_empty_list(cid, label, d, "card_type")
        check_old_style(cid, label, d)
        check_non_monster(cid, label, d)

    for cid, label in OLD_MONSTERS:
        d = cq.query_by_id(cid)
        check_not_null(cid, label, d, "name")
        check_non_empty_list(cid, label, d, "card_type")
        check_is_monster(cid, label, d)
        check_old_style(cid, label, d)

    cq.close()
    print(f"\n---\n{_passed} passed, {_failed} failed")
    return 0 if _failed == 0 else 1


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def _name(d: dict) -> str:
    return d.get("name") or f"id={d.get('id')}"


def check_not_null(cid: int, label: str, d: dict, field: str) -> None:
    if d.get(field) is not None:
        ok(cid, label, f"{field}={d[field]}")
    else:
        fail(cid, label, f"{field} is null")


def check_non_empty_list(cid: int, label: str, d: dict, field: str) -> None:
    val = d.get(field)
    if isinstance(val, list) and len(val) > 0:
        ok(cid, label, f"{field}={val}")
    else:
        fail(cid, label, f"{field} is empty list")


def check_new_style(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    ct = d["card_text"]
    if ct is not None:
        fail(cid, label, f"new card has card_text: {ct[:60]}")
        return
    if _is_normal_nonpend(d):
        ok(cid, n, "new-style texts (normal monster, all null)")
        return
    if _is_normal_pendulum(d):
        pe = d.get("p_effect_text"); pne = d.get("p_non_effect_text")
        if pe is not None or pne is not None:
            ok(cid, n, "new-style texts (normal pendulum, P effects exist)")
        else:
            fail(cid, label, "normal pendulum missing P effect texts")
        return
    et, ne = d["effect_text"], d["non_effect_text"]
    if et is None and ne is None:
        fail(cid, label, "new card has no effect_text nor non_effect_text")
        return
    ok(cid, n, "new-style texts")


def check_old_style(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    ct, et, ne = d["card_text"], d["effect_text"], d["non_effect_text"]
    if ct is None:
        fail(cid, label, "old card missing card_text")
    elif et is not None or ne is not None:
        fail(cid, label, "old card has new-style fields")
    else:
        ok(cid, n, "old-style texts")


def check_is_monster(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    if d.get("race") is None:
        fail(cid, label, "monster has null race")
    elif d.get("attribute") is None:
        fail(cid, label, "monster has null attribute")
    else:
        ok(cid, n, f"race={d['race']}, attr={d['attribute']}")


def check_non_monster(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    issues = []
    if d.get("race") is not None:
        issues.append(f"race={d['race']}")
    if d.get("attribute") is not None:
        issues.append(f"attr={d['attribute']}")
    if issues:
        fail(cid, n, f"non-monster has: {', '.join(issues)}")
    else:
        ok(cid, n, "non-monster (no race/attr)")


def check_pendulum(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    if d.get("pendulum_scales") is not None:
        ok(cid, n, f"scales={d['pendulum_scales']}")
    else:
        fail(cid, label, "pendulum missing scales")


def check_normal_texts(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    texts = [d[k] for k in ("non_effect_text","effect_text","card_text",
                             "p_effect_text","p_non_effect_text")]
    if any(t is not None for t in texts):
        fail(cid, label, "normal monster has non-null text")
    else:
        ok(cid, n, "all texts null")


def check_link(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    if not d.get("link_markers"):
        fail(cid, label, "link monster missing markers")
    elif d.get("def") is not None:
        fail(cid, label, f"link monster has def={d['def']}")
    else:
        ok(cid, n, f"markers={d['link_markers']}")


def check_xyz(cid: int, label: str, d: dict) -> None:
    n = _name(d)
    rk = d.get("rank")
    if rk is not None:
        ok(cid, n, f"rank={rk}")
    else:
        fail(cid, label, "XYZ missing rank")


def _is_normal_nonpend(d: dict) -> bool:
    ct = d.get("card_type") or []
    return "通常怪兽" in ct and "灵摆" not in ct


def _is_normal_pendulum(d: dict) -> bool:
    ct = d.get("card_type") or []
    return "通常怪兽" in ct and "灵摆" in ct


if __name__ == "__main__":
    sys.exit(run_all())
