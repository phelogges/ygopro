# 默认 HTTP v3 场景回放验证

> 状态：现行验证记录；截至 2026-10-11。仅记录已完成的 macOS 无头离线回放；现行操作见[回放指南](../guides/scenario-replay.md)，当前场景见[场景索引](../../tests/scenarios/README.md)。

`tools/agent-e2e.py` 默认使用 Agent HTTP v3。YAML 的 `schema_version: 1` 是场景格式版本，不是 HTTP v1。Host、Guest 各启动独立离线 Agent 子服务，通过共享脚本协调器选择动作，客户端仍用原有 LAN 游戏协议对局。未调用真实 LLM。

## 当前入库场景

2026-10-11 用户确认收录「天声的服从」卡名宣言场景后，当前目录有二十二个场景。本次仅回放 `tests/scenarios/lullaby-of-obedience-announce-card/scenario.yaml`；报告 `out/agent-e2e-runs/1791715314-65134/scenario-report.json` 为 HTTP v3 `passed`、`duel_finished`，Host 获胜，Host/Guest 均剩余 0 步且无忽略决策。两次宣言分别走特殊召唤与加入手牌分支，双端事件与后置快照断言通过。录制和限制见[宣言验证记录](announce-card-options-2026-10-11.md)。未运行其他二十一个场景，暂无二十二场景批量通过报告。

2026-10-11 收录「DNA 改造手术种族变化」后，当前目录有二十一个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/dna-surgery-race-change/scenario.yaml`；报告 `out/agent-e2e-runs/1791712595-5172/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，炎族／不死族→幻想魔族→电子界族的两阶段快照与双端通用数值事件断言通过。录制与候选回放见[种族变化记录](dna-surgery-race-change.md)。本次没有运行其他二十个场景，因此没有二十一场景的批量通过报告。

2026-10-11 收录「DNA 移植手术属性变化」后，当前目录有二十个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/dna-transplant-attribute-change/scenario.yaml`；报告 `out/agent-e2e-runs/1791711836-88148/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，暗／炎→神→风的两阶段快照和双端通用数值事件断言通过。录制与候选回放见[属性变化记录](dna-transplant-attribute-change.md)。本次没有运行其他十九个场景，因此没有二十场景的批量通过报告。

2026-10-11 收录「人偶兵卒①」后，当前目录有十九个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/doll-soldier-direct-attack/scenario.yaml`；报告 `out/agent-e2e-runs/1791708702-19299/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，对手仍有怪兽时直接攻击玩家、800 点伤害和后置 LP 断言通过。录制与候选回放见[人偶兵卒①记录](doll-soldier-direct-attack.md)。本次没有运行其他十八个场景，因此没有十九场景的批量通过报告。

2026-10-11 收录「神机王 乌尔①②」后，当前目录有十八个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/machine-king-ur-all-monsters-zero-damage/scenario.yaml`；报告 `out/agent-e2e-runs/1791701681-10150/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，同一只乌尔依次攻击两个不同目标、首次 1600 对 500 却无对方 LP 伤害，以及两次伤害步骤均无伤害事件的断言通过。录制与候选回放见[神机王 乌尔①②记录](machine-king-ur-all-monsters-zero-damage.md)。本次没有运行其他十七个场景，因此没有十八场景的批量通过报告。

2026-10-11 收录「长枪龙①」后，当前目录有十七个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/spear-dragon-piercing-damage/scenario.yaml`；报告 `out/agent-e2e-runs/1791700610-86465/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，攻击里侧守备怪兽、1900 对 500 战斗数值、单次 1400 点伤害及后置 LP 断言通过。录制与候选回放见[长枪龙①记录](spear-dragon-piercing-damage.md)。本次没有运行其他十六个场景，因此没有十七场景的批量通过报告。

2026-10-11 收录「哥布林德伯格①」后，当前目录有十六个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/goblinbergh-hand-special-summon/scenario.yaml`；报告 `out/agent-e2e-runs/1791699600-64217/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，Guest 与 Host 各自一次手牌特殊召唤及发动怪兽转守备的断言通过。录制与候选回放见[哥布林德伯格①记录](goblinbergh-hand-special-summon.md)。本次没有运行其他十五个场景，因此没有十六场景的批量通过报告。

2026-10-11 收录「炎王妃 火神不死鸟①」后，当前目录有十五个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/fire-king-consort-search/scenario.yaml`；报告 `out/agent-e2e-runs/1791699055-52112/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，手牌怪兽被破坏、从卡组检索、公开展示及自身等级变为 8 的断言通过。录制与候选回放见[炎王妃①记录](fire-king-consort-search.md)。本次没有运行其他十四个场景，因此没有十五场景的批量通过报告。

2026-10-11 收录「天岩户②」后，当前目录有十四个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/amanowato-end-phase-return/scenario.yaml`；报告 `out/agent-e2e-runs/1791698242-34003/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，结束阶段强制发动、怪兽区回手与隐藏手牌边界断言通过。录制与候选回放见[天岩户②记录](amanowato-end-phase-return.md)。本次没有运行其他十三个场景，因此没有十四场景的批量通过报告。

2026-10-11 收录「妖精传姬-辉夜②」后，当前目录有十三个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/fairy-tail-luna-bounce/scenario.yaml`；报告 `out/agent-e2e-runs/1791697496-17596/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，第一次成功回手两只怪兽与第二次送同名卡无效、零回手的断言均通过。录制与候选回放见[妖精传姬-辉夜②记录](fairy-tail-luna-bounce.md)。本次没有运行其他十二个场景，因此没有十三场景的批量通过报告。

2026-10-11 收录「心变①」后，当前目录有十二个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/change-of-heart-control/scenario.yaml`；报告 `out/agent-e2e-runs/1791696756-1291/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，取得与归还控制权的事件和场面断言通过。录制与候选回放见[心变①记录](change-of-heart-control.md)。本次没有运行其他十一个场景，因此没有十二场景的批量通过报告。

2026-10-11 收录「黑羽-热风之基布利②」后，当前目录有十一个场景。按用户要求只运行新场景的正式路径 `tests/scenarios/blackwing-gibli-stat-swap/scenario.yaml`；报告 `out/agent-e2e-runs/1791694514-64206/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽，攻守交换与回合结束恢复断言通过。原始录制和候选回放见[黑羽-热风之基布利②记录](blackwing-gibli-stat-swap.md)。本次没有运行其他十个场景，因而没有十一场景的批量通过报告。

2026-10-11 收录「河马狂欢节①」后，运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir`，当前十个场景的汇总报告位于 `out/agent-e2e-runs/batch-1791692520-20370/batch-report.json`：`passed: 10`、`failed: 0`、`unsupported: 0`。新增场景的 `scenario-004.json` 为 `passed`，双端检查三只衍生物的特殊召唤事件、格子与同一连锁中的准确次数；原始录制和独立回放见[河马狂欢节①记录](hippo-carnival-three-tokens.md)。批量入口检查场景包五个必需文件，机器通过只证明场景内已写的断言成立。

同日较早收录「魔导战士 破坏者③」后的九场景汇总报告位于 `out/agent-e2e-runs/batch-1791660037-29869/batch-report.json`：当时 `passed: 9`、`failed: 0`、`unsupported: 0`。新增场景的 `scenario-002.json` 为 `passed`，双端检查效果身份、指示物移除与魔陷卡带效果破坏标志进入墓地；原始录制和独立回放见[破坏者③记录](breaker-spell-trap-destroy.md)。此报告保留为当时证据，不再代表当前场景数量。

同日较早收录「俱舍怒威族·独角兽③」后的八场景汇总报告位于 `out/agent-e2e-runs/batch-1791654878-13235/batch-report.json`：当时 `passed: 8`、`failed: 0`、`unsupported: 0`。该场景在双方视角检查额外卡组展示、选择、移至里侧除外区以及处理后的隐藏信息边界；录制和独立回放证据见[独角兽③记录](kashtira-unicorn-extra-face-down-banish.md)。此报告保留为当时证据，不再代表当前场景数量。

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

当前二十二个入库场景中，最近新增的「天声的服从卡名宣言」「DNA 改造手术种族变化」「DNA 移植手术属性变化」「人偶兵卒①」「神机王 乌尔①②」「长枪龙①」「哥布林德伯格①」「炎王妃①」「天岩户②」「妖精传姬-辉夜②」「心变①」与「黑羽-热风之基布利②」各自在 macOS 默认 v3 无头离线链路中单独通过；另十个的最近批量通过证据来自这十二场收录之前。较早的九、八、七、六、五、四及删减前八场景结果仅保留历史证据。随机场景的 `single_passed` 不表示隐藏排列全覆盖。v3 GUI 播放、真实模型及 Windows 均须单独记录结果。
