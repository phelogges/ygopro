# 「人偶兵卒」①直接攻击录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/doll-soldier-direct-attack/`](../../tests/scenarios/doll-soldier-direct-attack/README.md)。现行格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `8c3c44951f82458c835ad48ae30ca1ec` 为不洗牌的单局 1v1。双端日志完整，实际提交的两副 40 张主卡组与收录的 YDK 一致；编译为 `compiled`（Host 3 步、Guest 9 步、无阻断），录制器自动回放为 `validated`。

Host 与 Guest 场上各有一只表侧攻击表示的「人偶兵卒」。Guest 的战斗命令攻击候选含 `direct_attackable: true`。第一次选择攻击后，Guest 拒绝 `description_id: 31` 的“是否直接攻击？”询问并取消选怪；第二次选择攻击后接受直接攻击。双方随后各观察到一次 `attack_declared`，攻击者为 Guest 怪兽区 3，攻击目标为 Host 玩家（`target_location: 0`，无目标怪兽序号）；`battle_values_observed` 为攻击力 800、目标区域 0，Host 怪兽仍在场。双方各观察到一次 Host 的 `life_points_damaged`，数值为 800。Guest 的下一决策快照显示 Host LP 由 8000 降至 7200；Host 随后投降只负责终局。

场景已补上双端有序事件、实际攻击到伤害步骤结束间的伤害次数，以及攻击前后场面和 LP 断言。候选路径报告 `out/agent-e2e-runs/1791708527-15417/scenario-report.json` 为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/doll-soldier-direct-attack/scenario.yaml`，报告 `out/agent-e2e-runs/1791708702-19299/scenario-report.json` 同样为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽；未运行其他十八个场景或十九场景批量回归。未验证攻击无效、伤害修正、②检索效果、真实模型、GUI 场景播放与 Windows。
