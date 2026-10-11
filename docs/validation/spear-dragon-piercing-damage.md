# 「长枪龙」①穿透伤害录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/spear-dragon-piercing-damage/`](../../tests/scenarios/spear-dragon-piercing-damage/README.md)。现行格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `49948629e6ec469b82665f7e5f56fdd6` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。双端日志与实际提交 YDK 完整；编译为 `compiled`（Host 6 步、Guest 3 步、无阻断），录制器自动验证为 `validated`。

Guest 第 1 回合将 33112041「火山鼠」里侧守备盖放于怪兽区 2。Host 第 2 回合通常召唤 31553716「长枪龙」，以表侧攻击表示向该里侧守备怪兽宣言攻击。Host 攻击前快照只知道对方怪兽区 2 有一只身份未知的里侧守备怪兽；剧本不借 Guest 手牌日志为 Host 提前补身份。伤害步骤中双方观察到目标翻为表侧守备，`battle_values_observed` 给出长枪龙攻击力 1900、目标守备力 500；随后 `life_points_damaged` 指向 Guest、`value=1400`。Guest LP 从 8000 降至 6600，符合 1900－500。目标以 `reason_flags=33` 战斗破坏进入墓地；长枪龙攻击后变为表侧守备。

①在战斗中适用，不产生单独的 `effect_activated` 事件。为避免只凭终局 LP 误判因果，本次扩展场景事件断言，允许精确匹配 `attack_declared` 的双方格子、`battle_values_observed` 的攻守值，以及 `life_points_damaged` 的受伤方和数值；并断言攻击至伤害步骤结束间恰好一次受伤事件。场景单元测试 35 项通过；补断言后仅回放本候选，报告 `out/agent-e2e-runs/1791700491-83761/scenario-report.json` 为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/spear-dragon-piercing-damage/scenario.yaml`，报告 `out/agent-e2e-runs/1791700610-86465/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽；未运行其他十六个场景或十七场景批量回归。Guest 在第 2 回合主要阶段 2 投降仅负责终局；原始 JSONL 不入 Git。此证据不覆盖守备力不低于攻击力、伤害无效或修正、重放攻击、真实模型、GUI 剧本播放或 Windows。
