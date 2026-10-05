"""Check that every C++ prompt fixture is accepted by the Python SDK."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_sdk import parse_request


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_codec_sdk.py /path/to/agent_codec_test")
    binary = Path(sys.argv[1])
    output = subprocess.check_output([binary, "--dump-prompts"], text=True)
    prompts = json.loads(output)
    for index, prompt in enumerate(prompts, 1):
        request = {
            "schema_version": 1,
            "session_id": "codec-fixture",
            "duel_id": "duel-fixture",
            "prompt_id": index,
            "database_sha256": "0" * 64,
            "deadline_unix_ms": None,
            "observation": {
                "self_player": 0,
                "turn_player": 0,
                "turn": 1,
                "phase": "main_1",
                "life_points": [8000, 8000],
                "zones": [],
                "events": [],
            },
            "prompt": prompt,
        }
        parse_request(request)
    print(f"{len(prompts)} C++ prompts accepted by Python SDK")


if __name__ == "__main__":
    main()
