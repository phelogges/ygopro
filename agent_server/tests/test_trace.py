"""The public timeline must not expose provider internals."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from pydantic_ai.messages import PartStartEvent, ThinkingPart

from agent_server.storage import StateDatabase
from agent_server.trace import TraceWriter, safe_value


class TraceTests(unittest.TestCase):
    def test_reasoning_summary_keeps_text_but_not_signature_or_provider_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with StateDatabase(Path(directory) / "state.sqlite3") as storage:
                writer = TraceWriter(storage, "session", "duel", "3:1")
                writer.accept(
                    PartStartEvent(
                        index=0,
                        part=ThinkingPart(
                            content="检查墓地",
                            signature="encrypted-secret",
                            provider_details={"raw_content": "private-provider-data"},
                        ),
                    )
                )
                writer.flush()
                events = storage.get_traces("session", "duel")
                self.assertEqual(events[-1]["payload"]["text"], "检查墓地")
                self.assertEqual(events[-1]["payload"]["form"], "text")
                writer.finish_response()
                events = storage.get_traces("session", "duel")
                self.assertEqual(events[-1]["kind"], "model_response_finished")
                self.assertEqual(events[-1]["response_id"], "3:1:r1")
                self.assertNotIn("encrypted-secret", str(events))
                self.assertNotIn("private-provider-data", str(events))

    def test_nested_sensitive_fields_are_removed(self) -> None:
        projected = safe_value({"tool": [{"token": "secret", "result": 7}], "signature": "secret"})
        self.assertEqual(projected, {"tool": [{"result": 7}]})

    def test_bounded_projection_marks_truncation(self) -> None:
        self.assertEqual(safe_value("abcdef", max_length=3), "abc[truncated]")
        projected = safe_value(list(range(101)))
        self.assertIsInstance(projected, list)
        self.assertEqual(cast(list[object], projected)[-1], "[items truncated]")
        recursive: list[object] = []
        recursive.append(recursive)
        self.assertIn("[nesting truncated]", str(safe_value(recursive)))


if __name__ == "__main__":
    unittest.main()
