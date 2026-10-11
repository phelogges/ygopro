# 「炎王妃 火神不死鸟」①检索怪兽录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/fire-king-consort-search/`](../../tests/scenarios/fire-king-consort-search/README.md)。现行格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端重录 `874ee16c4acb45c19a86d50ae1ab640a` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。先前录制 `521676047dea4c6e82e73bfb820994f9` 按用户要求忽略。重录双端日志、实际提交 YDK 和编译报告完整；编译为 `compiled`（Host 0 步、Guest 7 步、无阻断），自动验证为 `validated`。

第 1 回合，Guest 通常召唤 44455560「炎王妃 火神不死鸟」并接受①效果发动。Guest 在第一个 `select_cards` 提示选择自己手牌中的 33112041「火山鼠」，双端接收手牌至墓地的 `card_moved`（`reason_flags=65`）；Guest 后置墓地可见该卡。Guest 在第二个 `select_cards` 提示选择卡组中的 23015896「炎王神兽 大鹏不死鸟」，双端接收卡组至手牌的 `card_moved`（`reason_flags=64`）和包含该 ID 的 `cards_revealed`。随后 Guest 接受可选等级变化，双方场上 44455560 的等级由 4 变为 8。场景分别断言两端按序事件、两类移动各恰好一次及最终手牌、墓地、等级状态。

Host 知道展示过的 23015896，但其对手手牌快照仍为 4 张隐藏卡，`cards` 为空；没有把展示历史写成当前可见的手牌身份。补断言后仅回放这条候选，`out/agent-e2e-runs/1791698832-47164/scenario-report.json` 为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/fire-king-consort-search/scenario.yaml`；报告 `out/agent-e2e-runs/1791699055-52112/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽。本次未运行其他十四个场景或十五场景批量回归。Host 第 2 回合投降仅负责终局。原始 JSONL 不入 Git。此证据不覆盖其他检索目标、从场上破坏素材、效果无效、真实模型、GUI 剧本播放或 Windows。
