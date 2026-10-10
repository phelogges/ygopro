# 客户端游戏消息覆盖审计验证

> 状态：历史验证记录；截至 2026-10-10 的 macOS 本地结果。现行入口为[验证总览](README.md)，分类与待处理内容见[消息覆盖审计](../design/agent-message-coverage.md)。

本次比较原生客户端 `gframe/duelclient.cpp` 的游戏消息处理分支与 Agent 客户端的事件解析、明确忽略分支。检查结果为 86 类原生消息：41 类已有事件解析，27 类明确无需事件，18 类列入待处理清单。待处理消息在运行时仍使 `history_complete=false`，不会进入 Agent 自动决策。

| 验证 | 结果 |
| --- | --- |
| `python3 tools/check-agent-message-coverage.py` | 通过；86 / 41 / 27 / 18 |
| `python3 -m unittest tests.test_agent_message_coverage -v` | 通过；注入新的原生消息分支后，审计正确报出未分类 |
| `agent_sdk/.venv/bin/ruff check tools/check-agent-message-coverage.py tests/test_agent_message_coverage.py` | 通过 |
| `agent_sdk/.venv/bin/ruff format --check tools/check-agent-message-coverage.py tests/test_agent_message_coverage.py` | 通过 |
| `cmake --build --preset MacOS-Debug` | 通过；CMake 重新配置并构建客户端与协议测试 |
| `ctest --test-dir out/build/MacOS-Debug --output-on-failure` | 3/3 通过，包含新增 `agent_message_coverage` |
| `python3 tools/check-docs.py` | 通过；45 页 |

这项检查只防止原生消息分支**没有分类**。它不证明已解析事件的字段、隐藏信息遮蔽或事件因果正确；待处理的 14 类当前单局及赛前消息还需要真实双视角录制和逐类协议测试。Windows 构建与运行未验证。
