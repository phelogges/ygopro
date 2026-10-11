# 黑羽-热风之基布利②交换攻守录制与回放

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/blackwing-gibli-stat-swap/`](../../tests/scenarios/blackwing-gibli-stat-swap/README.md)。现行场景格式见[固定场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `15ddc47d60b04ef988b0ad636d4ed1e6` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张和无限时设置。中止的首次录制 `a325fc383b7f4655a19db905843f1156` 不作为证据。新录制的双方权威终局一致，Host 投降，Guest 获胜；编译器生成 Host 0 步、Guest 4 步，自动无头回放状态为 `validated`。

Guest 在第 1 回合主要阶段通常召唤 26775203 并发动其②效果。双方各自收到 `effect_activated`、`chain_link_solving`、`chain_link_solved` 与 `chain_ended`。Guest 录制快照 #120 的攻守和原本攻守均为 0／1600，#189 均为 1600／0，#254 回合结束时恢复 0／1600；Host 的对应快照 #106、#172、#238 也显示同样的公开变化。`scenario.yaml` 在 Guest 发动前与结算后检查这四个字段，下一回合在双端检查恢复；双端事件断言核对效果身份与连锁次序。

补断言后的独立 HTTP v3 双端无头回放报告 `out/agent-e2e-runs/1791694324-59993/scenario-report.json` 为 `passed`、`duel_finished`，双方步骤耗尽。用户确认收录后，只对正式路径 `tests/scenarios/blackwing-gibli-stat-swap/scenario.yaml` 做单场验收；报告 `out/agent-e2e-runs/1791694514-64206/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽。本次未运行其他十个剧本或十一场景批量回归。场景单元测试 34 项通过；Ruff 检查通过。该证据不覆盖效果无效、重叠数值修正、再次发动、离场重置、真实模型、GUI 播放或 Windows。
