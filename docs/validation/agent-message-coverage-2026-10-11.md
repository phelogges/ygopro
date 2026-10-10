# 当前单局游戏消息解析验证

> 状态：历史验证记录；截至 2026-10-11 的 macOS 本地结果。现行入口为[验证总览](README.md)，消息分类见[覆盖审计](../design/agent-message-coverage.md)。

本轮为上次审计发现的 14 类当前单局消息增加客户端事件解析，并让 Agent SDK 校验新增事件和牌库倒置快照。事件只带本客户端已收到的展示信息；交换与持续关系事件不复制原始卡片 ID。`MSG_MISSED_EFFECT` 的卡名会出现在原生 GUI 的可见日志，因此保留这次公开的卡片 ID，但遮蔽隐藏区域序号。`MSG_HAND_RES` 按卡片效果可能触发的对局内猜拳结果处理。

事件解析在最终结构中集中于 `gframe/agent_client/game_event_codec.h`，统一接入 `AgentController::RecordEvent`。既有随机结果、随机选卡、盖卡洗切与本轮补齐的消息使用同一个入口；覆盖检查核对消息登记和解析分支。

| 验证 | 结果 |
| --- | --- |
| `cmake --build --preset MacOS-Debug` | 通过 |
| `ctest --test-dir out/build/MacOS-Debug --output-on-failure` | 3/3 通过；C++ 测试覆盖 14 类消息的完整、截断、尾随字节及部分隐藏位置 |
| `agent_sdk/.venv/bin/python -m unittest discover -s agent_sdk/tests -p test_state.py -q` | 20/20 通过；包含新增事件入库、倒置状态和隐藏位置拒绝 |
| `agent_sdk/.venv/bin/python -m unittest discover -s agent_sdk/tests -q` | 98/98 通过；包含回环 HTTP 测试，在沙盒外执行 |
| `python3 -m unittest tests.test_agent_message_coverage -q` | 通过；注入未分类原生消息会失败 |
| `python3 tools/check-agent-message-coverage.py` | 86 类：55 已解析、27 明确无需事件、4 待处理 |
| `agent_sdk/.venv/bin/ruff check agent_sdk/src/agent_sdk/state.py agent_sdk/tests/test_state.py tools/check-agent-message-coverage.py tests/test_agent_message_coverage.py` | 通过 |
| 从 `agent_sdk/` 运行 `.venv/bin/pyright src/agent_sdk/state.py` | 0 错误 |
| `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir` | 最终代码再次按默认 HTTP v3 回放，四场景 4/4 通过；本机报告 `out/agent-e2e-runs/batch-1791649238-6959/batch-report.json` |
| 统一事件模块重构后 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/magical-hats-set-shuffle/scenario.yaml` | `checkpoint_passed`；本机报告 `out/agent-e2e-runs/1791649856-18048/scenario-report.json` |
| `python3 tools/check-docs.py` | 通过；47 页 |

现有四场景不逐一触发本轮全部 14 类消息。字节级单测与批量回放不能代替对应效果的真实双客户端录制；事件顺序和双方可见边界还须用新场景复核。Windows 构建及运行未验证。
