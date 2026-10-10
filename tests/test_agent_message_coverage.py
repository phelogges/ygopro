"""New native duel messages must be classified before Agent use."""

from __future__ import annotations

import runpy
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


class MessageCoverageTests(unittest.TestCase):
    def test_native_message_added_without_classification_fails(self) -> None:
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(str(root / "tools/check-agent-message-coverage.py"))
        audit = cast(Any, namespace["audit"])
        classification, errors = audit(root)
        self.assertFalse(errors)
        self.assertEqual(classification["MSG_SHUFFLE_SET_CARD"], "decoded")
        self.assertEqual(classification["MSG_EQUIP"], "decoded")
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = Path(temporary)
            for relative in (
                "ocgcore/common.h",
                "gframe/network.h",
                "gframe/duelclient.cpp",
                "gframe/agent_client/agent_controller.cpp",
                "gframe/agent_client/game_event_codec.h",
                "tools/agent-message-coverage.json",
            ):
                target = copy_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / relative, target)
            with (copy_root / "gframe/network.h").open("a", encoding="utf-8") as file:
                file.write("\n#define MSG_TEST_NEW_EVENT 250\n")
            with (copy_root / "gframe/duelclient.cpp").open(
                "a", encoding="utf-8"
            ) as file:
                file.write("\ncase MSG_TEST_NEW_EVENT:\n")
            _, errors = audit(copy_root)
            self.assertIn(
                "MSG_TEST_NEW_EVENT: native message has no Agent classification", errors
            )
            helper_path = copy_root / "gframe/agent_client/game_event_codec.h"
            helper = helper_path.read_text(encoding="utf-8")
            helper_path.write_text(
                helper.replace(
                    "  case MSG_HAND_RES:\n    return true;",
                    "  case MSG_HAND_RES:\n  case MSG_TEST_NEW_EVENT:\n    return true;",
                    1,
                ),
                encoding="utf-8",
            )
            _, errors = audit(copy_root)
            self.assertIn(
                "MSG_TEST_NEW_EVENT: game event registration and parser disagree",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
