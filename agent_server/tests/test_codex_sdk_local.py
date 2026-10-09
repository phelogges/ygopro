"""Offline startup check for the SDK's bundled app-server and MCP config."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest
from openai_codex import ApprovalMode, AsyncCodex, Sandbox

from agent_server.codex_agent import codex_settings
from agent_server.codex_mcp_bridge import CodexMcpBridge


@pytest.mark.skipif(sys.platform == "win32", reason="Windows MCP IPC is pending validation")
def test_bundled_codex_starts_with_duel_mcp_without_login() -> None:
    async def run() -> None:
        bridge = CodexMcpBridge()
        await bridge.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "codex_home"
                workspace = Path(directory) / "workspace"
                home.mkdir()
                workspace.mkdir()
                (workspace / ".ygopro-agent-root").touch()
                async with AsyncCodex(codex_settings(home, workspace, bridge)) as codex:
                    account = await codex.account()
                    assert account.account is None
                    thread = await codex.thread_start(
                        approval_mode=ApprovalMode.deny_all,
                        sandbox=Sandbox.read_only,
                        cwd=str(workspace),
                    )
                    assert thread.id
        finally:
            await bridge.close()

    asyncio.run(run())
