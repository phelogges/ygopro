import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_sdk.recording_compiler import (
    RecordingError,
    _expect,  # pyright: ignore[reportPrivateUsage]
    _normalize_places,  # pyright: ignore[reportPrivateUsage]
    _public_change_summary,  # pyright: ignore[reportPrivateUsage]
    compile_recording,
)
from agent_sdk.scenario import Scenario


def _prompt(kind: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": kind, "description": "", "constraints": {}, "candidates": candidates}


def _candidate(cid: str, kind: str, card_id: int | None = None) -> dict[str, Any]:
    candidate: dict[str, Any] = {"id": cid, "kind": kind, "description": ""}
    if card_id is not None:
        candidate["card"] = {"card_id": card_id, "controller": 0, "location": "hand", "sequence": 0}
    return candidate


def _capture(role: str, record_id: str = "test-capture") -> list[dict[str, Any]]:
    observation = {"turn": 1, "phase": "main_1", "turn_player": 0}
    result: list[dict[str, Any]] = []

    def add(kind: str, **fields: Any) -> None:
        result.append(
            {
                "kind": kind,
                "seq": len(result) + 1,
                "role": role,
                "timestamp_unix_ms": len(result) + 1,
                **fields,
            }
        )

    add("session", record_id=record_id)
    add("room_joined", mode=0, no_shuffle_deck=True, no_check_deck=True)
    add("deck_submitted", main=[100, 101, 102, 103, 104], extra=[], side=[])
    add(
        "prompt",
        prompt_id=1,
        prompt=_prompt(
            "rock_paper_scissors", [_candidate("c0", "rock"), _candidate("c1", "paper")]
        ),
        observation=observation,
        auto_answered=False,
    )
    add(
        "response",
        prompt_id=1,
        action={"kind": "choice", "candidate_id": "c0" if role == "host" else "c1"},
    )
    if role == "guest":
        add(
            "prompt",
            prompt_id=2,
            prompt=_prompt(
                "first_player", [_candidate("c0", "go_first"), _candidate("c1", "go_second")]
            ),
            observation=observation,
            auto_answered=False,
        )
        add("response", prompt_id=2, action={"kind": "choice", "candidate_id": "c0"})
    add("duel_start")
    if role == "host":
        add(
            "prompt",
            prompt_id=3,
            prompt=_prompt("idle_command", [_candidate("c0", "normal_summon", 100)]),
            observation=observation,
            auto_answered=False,
        )
        add("response", prompt_id=3, action={"kind": "choice", "candidate_id": "c0"})
    add(
        "visible_snapshot",
        message_type=5,
        observation={
            "turn": 1,
            "life_points": [8000, 8000],
            "zones": [
                {"player": player, "name": name, "count": 0, "cards": []}
                for player in (0, 1)
                for name in ("monster", "spell", "graveyard", "banished")
            ],
        },
    )
    add("duel_end", winner="guest")
    return result


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class RecordingCompilerTests(unittest.TestCase):
    def test_visible_expect_uses_card_without_hand_slot_and_field_result(self) -> None:
        previous: dict[str, Any] = {
            "zones": [{"player": 0, "name": "monster", "count": 0, "cards": []}]
        }
        observation = {
            "turn": 1,
            "phase": "main_1",
            "turn_player": 0,
            "zones": [
                {
                    "player": 0,
                    "name": "hand",
                    "count": 1,
                    "cards": [{"card_id": 100, "sequence": 2, "position": "face_down_defense"}],
                },
                {
                    "player": 0,
                    "name": "monster",
                    "count": 1,
                    "cards": [{"card_id": 200, "sequence": 3, "position": "face_up_attack"}],
                },
            ],
        }
        action = {
            "kind": "choice",
            "match": {
                "kind": "activate",
                "card_id": "00000100",
                "controller": 0,
                "location": "hand",
            },
        }
        expect = _expect(_prompt("idle_command", []), observation, action, previous)
        zones = {(z["player"], z["name"]): z for z in expect["zones"]}
        self.assertEqual(zones[(0, "hand")]["contains"], [{"card_id": "00000100"}])
        self.assertEqual(
            zones[(0, "monster")]["contains"],
            [{"card_id": "00000200", "position": "face_up_attack", "sequence": 3}],
        )

    def test_legacy_raw_and_local_select_place_controllers(self) -> None:
        prompt = _prompt(
            "select_place",
            [{"id": "c0", "kind": "place", "controller": 0, "location": "monster", "sequence": 2}],
        )
        raw = {
            "seq": 12,
            "action": {
                "kind": "select_places",
                "places": [{"controller": 1, "location": "monster", "sequence": 2}],
            },
        }
        self.assertEqual(
            _normalize_places("guest", prompt, raw, "host", None),
            [{"controller": 0, "location": "monster", "sequence": 2}],
        )
        local: dict[str, Any] = {
            "seq": 13,
            "action": {
                "kind": "select_places",
                "places": [{"controller": 0, "location": "monster", "sequence": 2}],
            },
        }
        self.assertEqual(
            _normalize_places("guest", prompt, local, "host", "local"), local["action"]["places"]
        )
        with self.assertRaises(RecordingError):
            _normalize_places("guest", prompt, raw, "host", "local")

    def test_compiles_paired_capture_to_scenario_and_decks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            for role in ("host", "guest"):
                _write(source / f"{role}.jsonl", _capture(role))
            output = Path(directory) / "draft"
            cards_db = Path(directory) / "cards.cdb"
            with sqlite3.connect(cards_db) as connection:
                connection.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, name TEXT)")
                connection.execute("INSERT INTO texts VALUES (100, '测试卡')")
            report = compile_recording(source, output, cards_db)
            self.assertEqual(report["status"], "compiled")
            scenario = Scenario.load(output / "scenario.yaml")
            self.assertEqual(scenario.goal["winner"], "guest")
            self.assertEqual(len(scenario.steps["host"]), 1)
            self.assertEqual(
                scenario.steps["host"][0]["action"]["match"],
                {"kind": "normal_summon", "card_id": 100, "controller": 0, "location": "hand"},
            )
            self.assertIn("#main\n100\n101\n", (output / "host.ydk").read_text())
            self.assertIn('"00000100"', (output / "scenario.yaml").read_text())
            self.assertIn("提示 #", (output / "timeline.md").read_text())
            self.assertIn("回合 1，阶段 main_1，行动玩家 0", (output / "timeline.md").read_text())
            self.assertIn("《测试卡》（00000100）", (output / "timeline.md").read_text())

    def test_public_change_summary_only_uses_public_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before: dict[str, Any] = {
                "life_points": [8000, 8000],
                "zones": [
                    {"player": 0, "name": "monster", "count": 0, "cards": []},
                    {"player": 0, "name": "hand", "count": 5, "cards": []},
                ],
            }
            after: dict[str, Any] = {
                "life_points": [7500, 8000],
                "zones": [
                    {
                        "player": 0,
                        "name": "monster",
                        "count": 1,
                        "cards": [{"card_id": 100, "sequence": 0}],
                    },
                    {"player": 0, "name": "hand", "count": 4, "cards": []},
                ],
            }
            summary = _public_change_summary(before, after, Path(directory) / "absent.cdb")
            self.assertIn("玩家0 LP 8000→7500", summary)
            self.assertIn("玩家0怪兽区 0→1，新增 卡片 00000100", summary)
            self.assertNotIn("手牌", summary)

    def test_random_room_settings_only_emit_unverified_analysis_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            for role in ("host", "guest"):
                records = _capture(role)
                room = next(item for item in records if item["kind"] == "room_joined")
                room["no_shuffle_deck"] = False
                room["no_check_deck"] = False
                _write(source / f"{role}.jsonl", records)
            output = Path(directory) / "draft"
            self.assertEqual(compile_recording(source, output)["status"], "incomplete")
            report = compile_recording(source, output, analysis_draft=True)
            self.assertEqual(report["status"], "draft_unverified")
            self.assertEqual(len(report["blockers"]), 2)
            self.assertTrue((output / "scenario.unverified.yaml").is_file())
            self.assertFalse((output / "scenario.yaml").exists())

    def test_deck_check_enabled_does_not_change_duel_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            for role in ("host", "guest"):
                records = _capture(role)
                room = next(item for item in records if item["kind"] == "room_joined")
                room["no_check_deck"] = False
                _write(source / f"{role}.jsonl", records)
            self.assertEqual(
                compile_recording(source, Path(directory) / "draft")["status"], "compiled"
            )

    def test_unpaired_prompt_keeps_incomplete_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            _write(
                source / "host.jsonl",
                [
                    r
                    for r in _capture("host")
                    if not (r["kind"] == "response" and r.get("prompt_id") == 3)
                ],
            )
            _write(source / "guest.jsonl", _capture("guest"))
            output = Path(directory) / "draft"
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("prompt without response", report["errors"][0])
            self.assertTrue((output / "compile-report.json").exists())

    def test_rejects_random_event_and_recorder_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            host = _capture("host")
            host[-1]["seq"] += 1
            host.insert(
                -1,
                {
                    "kind": "visible_snapshot",
                    "seq": host[-1]["seq"] - 1,
                    "role": "host",
                    "message_type": 130,
                },
            )
            _write(source / "host.jsonl", host)
            _write(source / "guest.jsonl", _capture("guest"))
            report = compile_recording(source, Path(directory) / "draft")
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("uncontrolled random event coin", report["errors"][0])
            draft = compile_recording(source, Path(directory) / "draft", analysis_draft=True)
            self.assertEqual(draft["status"], "draft_unverified")
            self.assertIn("uncontrolled random event coin", draft["blockers"][0])
            self.assertTrue((Path(directory) / "draft/scenario.unverified.yaml").is_file())
            self.assertFalse((Path(directory) / "draft/scenario.yaml").exists())
            host[-2] = {
                "kind": "error",
                "seq": host[-2]["seq"],
                "role": "host",
                "code": "rejected_response",
            }
            _write(source / "host.jsonl", host)
            report = compile_recording(source, Path(directory) / "draft")
            self.assertIn("rejected_response", report["errors"][0])

    def test_latest_submitted_deck_and_auto_decline_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            host = _capture("host")
            start = next(i for i, item in enumerate(host) if item["kind"] == "duel_start")
            host.insert(
                start,
                {
                    "kind": "deck_submitted",
                    "role": "host",
                    "seq": 0,
                    "main": [201, 202, 203, 204, 205],
                    "extra": [],
                    "side": [],
                },
            )
            for seq, item in enumerate(host, 1):
                item["seq"] = seq
            guest = _capture("guest")
            end = guest.pop()
            guest.extend(
                [
                    {
                        "kind": "prompt",
                        "role": "guest",
                        "seq": 0,
                        "prompt_id": 3,
                        "prompt": _prompt(
                            "chain", [_candidate("c0", "activate", 100), _candidate("c1", "pass")]
                        ),
                        "observation": {"turn": 1, "phase": "main_1", "turn_player": 0},
                        "auto_answered": True,
                    },
                    {
                        "kind": "response",
                        "role": "guest",
                        "seq": 0,
                        "prompt_id": 3,
                        "action": {"kind": "choice", "candidate_id": "c1"},
                    },
                    end,
                ]
            )
            for seq, item in enumerate(guest, 1):
                item["seq"] = seq
            _write(source / "host.jsonl", host)
            _write(source / "guest.jsonl", guest)
            output = Path(directory) / "draft"
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "compiled")
            self.assertIn("#main\n201\n202\n", (output / "host.ydk").read_text())
            self.assertIn("有可发动候选，选择不发动", (output / "timeline.md").read_text())
            scenario = Scenario.load(output / "scenario.yaml")
            self.assertEqual(len(scenario.steps["guest"]), 1)

    def test_surrender_creates_role_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            for role in ("host", "guest"):
                records = _capture(role)
                ending = records.pop()
                records.append(
                    {
                        "kind": "visible_snapshot",
                        "role": role,
                        "observation": {"turn": 1, "phase": "main_1", "turn_player": 0},
                        "timestamp_unix_ms": 100,
                    }
                )
                if role == "host":
                    records.append({"kind": "surrender", "role": role, "timestamp_unix_ms": 200})
                records.append(ending)
                for seq, record in enumerate(records, 1):
                    record["seq"] = seq
                _write(source / f"{role}.jsonl", records)
            output = Path(directory) / "draft"
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "compiled")
            scenario = Scenario.load(output / "scenario.yaml")
            self.assertEqual(scenario.goal["surrender"]["role"], "host")

    def test_ambiguous_candidate_uses_verified_ordinal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            host = _capture("host")
            prompt = next(r for r in host if r["kind"] == "prompt" and r["prompt_id"] == 3)
            prompt["prompt"]["candidates"] = [
                _candidate("c0", "normal_summon", 100),
                _candidate("c1", "normal_summon", 100),
            ]
            for sequence, candidate in enumerate(prompt["prompt"]["candidates"], 1):
                candidate["card"]["sequence"] = sequence
                candidate["card"]["position"] = 4
                candidate["description_id"] = 0
                candidate["effect_flag"] = 0
            response = next(r for r in host if r["kind"] == "response" and r["prompt_id"] == 3)
            response["action"]["candidate_id"] = "c1"
            _write(source / "host.jsonl", host)
            _write(source / "guest.jsonl", _capture("guest"))
            output = Path(directory) / "draft"
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "compiled")
            usage = report["ordinal_usages"][0]
            self.assertEqual(usage["key"], f"host:{response['seq']}:c1")
            self.assertEqual((usage["ordinal"], usage["expected_matches"]), (2, 2))
            self.assertEqual(
                usage["selector"],
                {
                    "kind": "normal_summon",
                    "card_id": "00000100",
                    "controller": 0,
                    "location": "hand",
                },
            )
            self.assertTrue((output / "scenario.yaml").exists())
            self.assertFalse((output / "review-needed.json").exists())
            overrides = source / "overrides.json"
            overrides.write_text(
                json.dumps({usage["key"]: {"ordinal": 1, "expected_matches": 2}}),
                encoding="utf-8",
            )
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("disagrees with recorded candidate order", report["errors"][0])
            overrides.write_text(
                json.dumps({usage["key"]: {"ordinal": 2, "expected_matches": 2}}),
                encoding="utf-8",
            )
            report = compile_recording(source, output)
            self.assertEqual(report["status"], "compiled")
            scenario = Scenario.load(output / "scenario.yaml")
            selector = scenario.steps["host"][0]["action"]["match"]
            self.assertEqual((selector["ordinal"], selector["expected_matches"]), (2, 2))
            self.assertNotIn("sequence", selector)
            self.assertNotIn("position", selector)
            self.assertNotIn("description_id", selector)
            self.assertNotIn("effect_flag", selector)

    def test_rejects_different_public_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture"
            source.mkdir()
            host = _capture("host")
            guest = _capture("guest")
            terminal = next(r for r in guest if r.get("message_type") == 5)
            terminal["observation"]["life_points"] = [7500, 8000]
            _write(source / "host.jsonl", host)
            _write(source / "guest.jsonl", guest)
            report = compile_recording(source, Path(directory) / "draft")
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("life points differ", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
