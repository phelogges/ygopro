# 默认 HTTP v3 场景回放验证

> 状态：现行验证记录；截至 2026-10-10。仅记录已完成的 macOS 无头离线回放；现行操作见[回放指南](../guides/scenario-replay.md)，当前场景见[场景索引](../../tests/scenarios/README.md)。

`tools/agent-e2e.py` 默认使用 Agent HTTP v3。YAML 的 `schema_version: 1` 是场景格式版本，不是 HTTP v1。Host、Guest 各启动独立离线 Agent 子服务，通过共享脚本协调器选择动作，客户端仍用原有 LAN 游戏协议对局。未调用真实 LLM。

## 当前入库场景

用户移除旧剧本后，2026-10-10 运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir`，当前三个场景的汇总报告位于 `out/agent-e2e-runs/batch-1791624070-47995/batch-report.json`：`total: 3`、`passed: 3`、`failed: 0`、`unsupported: 0`。分别是 `death-camel-self-set`、`snake-eye-deck-set` 和 `tenpai-field-set`；每场都有独立双端诊断和 `scenario-report.json`。批量入口检查场景包五个必需文件，机器通过只证明场景内已写的断言成立。

## 已移除剧本的历史基线

同日较早的一次批量回放覆盖当时的八个场景，汇总报告位于 `out/agent-e2e-runs/batch-1791623524-37743/batch-report.json`：`total: 8`、`passed: 8`、`failed: 0`、`unsupported: 0`。下表是那次删减前的逐局证据；其中 `fixed-opening`、`duel-001`、`duel-002`、`summon-chain`、`surrender-smoke` 已不在当前回归集，不能据此宣称它们现在仍受批量测试覆盖。

| 场景 | 本机报告 | 实际结果 |
| --- | --- | --- |
| `fixed-opening` | `out/agent-e2e-runs/1791619290-61925/scenario-report.json` | `agent_http_protocol: v3`、`passed`、双方固定起手检查点通过 |
| `duel-001` | `out/agent-e2e-runs/1791619315-62412/scenario-report.json` | `agent_http_protocol: v3`、`passed`、Guest 获胜、双端权威终局 |
| `duel-002` | `out/agent-e2e-runs/1791622843-25363/scenario-report.json` | `agent_http_protocol: v3`、`passed`、Host 获胜、双端权威终局与场面断言通过 |
| `snake-eye-deck-set` | `out/agent-e2e-runs/1791619393-63783/scenario-report.json` | `agent_http_protocol: v3`、`passed`、Guest 获胜、展示与盖卡断言通过 |
| `summon-chain` | `out/agent-e2e-runs/1791623017-28530/scenario-report.json` | `agent_http_protocol: v3`、`passed`、固定起手及连锁检查点通过 |
| `tenpai-field-set` | `out/agent-e2e-runs/1791623044-29003/scenario-report.json` | `agent_http_protocol: v3`、`passed`、Host 获胜、场地区盖放断言通过 |
| `surrender-smoke` | `out/agent-e2e-runs/1791623076-29570/scenario-report.json` | `agent_http_protocol: v3`、`passed`、Host 投降、Guest 获胜 |
| `death-camel-self-set` | `out/agent-e2e-runs/1791623095-29897/scenario-report.json` | `agent_http_protocol: v3`、`passed`、怪兽转为里侧表示断言通过 |

运行目录均有双端诊断 JSONL。逐条核对可见每端首次决策携带 `deck_manifest`，每端收到一次 `inspect_zone` 手牌查询结果，并为已提交动作写入 `action_result_request`。终局场景的两端日志均记录 `terminal_sync_request`；`fixed-opening` 只到检查点，不要求终局。`duel-001` 的 Guest 最后一个提示在 Host 投降时取消，因此其决策请求数比动作回执数多一条，这是预期终局边界。场景事件断言读取各端 v3 服务已接受的本视角日志。

同日运行默认 `--games 3 --deck deck/test/test.ydk`，目录为 `out/agent-e2e-runs/1791619419-64253/`。三局的 `game-{1,2,3}-{host,guest}.json` 都记录 `status: finished`、`duel_end: true`，每局双方看到相同的胜者。该入口使用 v3 双端独立服务，但无 YAML 场景断言。另以显式 `--protocol v2` 回放 `fixed-opening`，`out/agent-e2e-runs/1791619914-73111/scenario-report.json` 为 `passed`，证明历史兼容入口仍可运行。

当前三个入库场景在 macOS 默认 v3 无头离线链路中通过；较早的八场景结果仅保留历史证据。v3 GUI 播放、真实模型及 Windows 均须单独记录结果。
