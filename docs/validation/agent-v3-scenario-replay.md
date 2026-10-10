# 默认 HTTP v3 场景回放验证

> 状态：现行验证记录；截至 2026-10-11。仅记录已完成的 macOS 无头离线回放；现行操作见[回放指南](../guides/scenario-replay.md)，当前场景见[场景索引](../../tests/scenarios/README.md)。

`tools/agent-e2e.py` 默认使用 Agent HTTP v3。YAML 的 `schema_version: 1` 是场景格式版本，不是 HTTP v1。Host、Guest 各启动独立离线 Agent 子服务，通过共享脚本协调器选择动作，客户端仍用原有 LAN 游戏协议对局。未调用真实 LLM。

## 当前入库场景

2026-10-11 收录「俱舍怒威族·独角兽③」后，运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir --timeout 180`，当前八个场景的汇总报告位于 `out/agent-e2e-runs/batch-1791654878-13235/batch-report.json`：`passed: 8`、`failed: 0`、`unsupported: 0`。新增场景在双方视角检查额外卡组展示、选择、移至里侧除外区以及处理后的隐藏信息边界；录制和独立回放证据见[独角兽③记录](kashtira-unicorn-extra-face-down-banish.md)。批量入口检查场景包五个必需文件，机器通过只证明场景内已写的断言成立。

同日较早收录「连续速攻魔法卡连锁」后的七场景汇总报告位于 `out/agent-e2e-runs/batch-1791653689-86101/batch-report.json`：当时 `passed: 7`、`failed: 0`、`unsupported: 0`。该场景在双方视角检查十项连锁依次加入、逆序处理及区间内恰好十项；录制和独立回放证据见[十项连锁记录](quick-play-ten-link-chain.md)。此报告保留为当时证据，不再代表当前场景数量。

同日较早收录「天子的指轮②」后的六场景汇总报告位于 `out/agent-e2e-runs/batch-1791652635-66669/batch-report.json`：当时 `passed: 6`、`failed: 0`、`unsupported: 0`。该场景验证对方魔法卡效果在处理时被自动无效，没有额外连锁项；录制和独立回放证据见[天子的指轮②记录](angel-ring-mandatory-spell-negation.md)。此报告保留为当时证据，不再代表当前场景数量。

同日较早收录「雷火沸动交界机③」后的五场景报告位于 `out/agent-e2e-runs/batch-1791651674-49898/batch-report.json`：当时 `passed: 5`、`failed: 0`、`unsupported: 0`。该场景验证目标怪兽效果被无效，且双端已接受事件中，该效果发动至连锁结束之间各只有一个 `chain_link_added`。原始录制与独立回放证据见[非连锁无效记录](raikasen-nonchain-negation.md)。此报告保留为当时证据，不再代表当前场景数量。

2026-10-10 收录「魔术礼帽」后的四场景报告位于 `out/agent-e2e-runs/batch-1791646840-63179/batch-report.json`：当时 `total: 4`、`passed: 4`、`failed: 0`、`unsupported: 0`。三个严格场景分别完成独立双端回放；`magical-hats-set-shuffle` 通过随机采样入口完成一次双端 checkpoint，状态为 `single_passed`、结果为 `count:3`。此报告保留为当时的证据，不再代表当前场景数量。

较早删减后的三场景报告位于 `out/agent-e2e-runs/batch-1791624070-47995/batch-report.json`，当时 `total: 3`、`passed: 3`。该报告保留为历史证据，不代表新增场景的结果。

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

当前八个入库场景在 macOS 默认 v3 无头离线链路中通过；较早的七、六、五、四及删减前八场景结果仅保留历史证据。随机场景的 `single_passed` 不表示隐藏排列全覆盖。v3 GUI 播放、真实模型及 Windows 均须单独记录结果。
