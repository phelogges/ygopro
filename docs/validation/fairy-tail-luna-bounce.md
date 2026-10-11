# 「妖精传姬-辉夜」②返回手牌与无效分支录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/fairy-tail-luna-bounce/`](../../tests/scenarios/fairy-tail-luna-bounce/README.md)。现行场景格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `85475b5b1e3a400e8f398c4b94c1eea5` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张和无限时设置。双端日志、实际提交的 YDK 与编译报告完整；自动编译 Host 11 步、Guest 10 步，原始无头验证状态 `validated`。Guest 投降，双方权威终局一致，Host 获胜。

第 2 回合，Guest 连锁发动 86937530 的②效果，以 Host 场上 33112041 为对象。Host 选择“否”（`description_id=1214`），未送同名卡；双方各收到两次怪兽区至手牌的 `card_moved`（`reason_flags=64`），以及之后的手牌洗切事件。Host 后续本方手牌中 33112041 从两张变三张，Guest 后续本方手牌中可见 86937530；双方怪兽区均为空。候选场景在双端分别断言效果身份、两次移动顺序及该连锁内到手牌的准确次数。

第 4 回合，Host 发动同一②效果，以 Guest 场上 40575313 为对象。Guest 选择“是”（`description_id=1213`），从卡组送出同名卡；双方事件流包含卡组至墓地移动和 `chain_link_disabled`。候选场景断言该连锁内到手牌移动次数为零，终局前辉夜和目标怪兽均留场。这是录制过程中额外出现的确定性分支，主目标仍是第 2 回合的成功弹回。

补断言后的独立 HTTP v3 双端无头回放报告 `out/agent-e2e-runs/1791697320-13696/scenario-report.json` 为 `passed`、`duel_finished`，双方步骤耗尽。用户确认收录后，仅对正式路径 `tests/scenarios/fairy-tail-luna-bounce/scenario.yaml` 执行单场验收；报告 `out/agent-e2e-runs/1791697496-17596/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽。本次未运行其他十二个剧本或十三场景批量回归。场景显式允许不影响按 ID 匹配的 `hand_shuffle`；没有把洗切后的手牌序号作为断言。目标选择候选本身未带卡片 ID，场上目标身份从同一提示的公开快照确认。此证据不覆盖额外卡组怪兽、目标离场、真实模型、GUI 场景播放或 Windows。
