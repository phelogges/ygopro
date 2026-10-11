# 「哥布林德伯格」①手牌特殊召唤录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/goblinbergh-hand-special-summon/`](../../tests/scenarios/goblinbergh-hand-special-summon/README.md)。现行格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `5d35df7a0c28434b83ae9dbd064372b7` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。双端日志、实际提交的 YDK 和编译报告完整；编译为 `compiled`（Host 8 步、Guest 7 步、无阻断），录制器自动验证为 `validated`。

Guest 在第 1 回合通常召唤 25259669「哥布林德伯格」，接受①效果，从手牌选 66707058「哥布林暗杀部队」并指定怪兽区 3、表侧守备表示。双端事件包含 Guest 手牌至怪兽区的 `card_moved`（`reason_flags=2048`）、带身份和格子的 `special_summon_started`、`special_summon_finished`，随后怪兽区 1 的哥布林德伯格 `position_changed` 为表侧攻击→表侧守备。Guest 后置手牌由 4 张变 3 张、怪兽区由 1 张变 2 张。

Host 在第 2 回合也通常召唤 25259669，接受①效果，从手牌选 33112041「火山鼠」并指定怪兽区 1、表侧攻击表示。双端接收对应的手牌至怪兽区移动、火山鼠特殊召唤开始与完成，以及怪兽区 2 的哥布林德伯格转为表侧守备。Host 后置手牌由 5 张变 4 张、怪兽区由 1 张变 2 张。

场景分别在 Host、Guest 视角断言两次效果的发动身份、特殊召唤移动与公开卡片 ID、结束后表示形式，并要求每个效果连锁内恰好一次 `special_summon_started`。补断言后只回放本候选，`out/agent-e2e-runs/1791699447-60771/scenario-report.json` 为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/goblinbergh-hand-special-summon/scenario.yaml`，报告 `out/agent-e2e-runs/1791699600-64217/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽；未运行其他十五个场景或十六场景批量回归。Host 在第 2 回合主要阶段 2 投降仅用于终局；原始 JSONL 不入 Git。此证据不覆盖效果无效、特殊召唤失败、里侧特殊召唤、其他等级怪兽、真实模型、GUI 剧本播放或 Windows。
