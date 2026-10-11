# 「长枪龙」①攻击守备怪兽造成穿透伤害

> 状态：经用户审核并收录的严格场景。来源：人工双客户端录制 `49948629e6ec469b82665f7e5f56fdd6`，2026-10-11，macOS Debug。

## 测试目标与结论

用户原话和整理目标见 [goal.md](goal.md)。Guest 在第 1 回合把「火山鼠」（33112041）里侧守备表示盖放。Host 在第 2 回合通常召唤「长枪龙」（31553716），攻击这只盖放怪兽。伤害步骤中目标翻开，双端收到长枪龙攻击力 1900、火山鼠守备力 500 的战斗数值和对 Guest 的单次 1400 点伤害；Guest LP 从 8000 变为 6600。目标 **已验证**。

| 核查点 | 双端证据与剧本断言 | 结论 |
| --- | --- | --- |
| 守备怪兽成为攻击对象 | Guest 盖放怪兽区 2；Host 攻击前只看见该格为身份未知的里侧守备怪兽；双端 `attack_declared` 指向该格 | 已验证 |
| 伤害计算数值 | 伤害步骤先有目标从里侧守备变表侧守备的 `position_changed`，再有 `battle_values_observed`：攻击力 1900、守备力 500 | 已验证 |
| 穿透伤害 | 双端收到防守方 `life_points_damaged.value=1400`，且 `1900－500=1400`；战斗前后 LP 为 8000→6600，攻击宣言至伤害步骤结束间恰有一次伤害事件 | 已验证 |
| 战斗结束状态 | 火山鼠以 `reason_flags=33` 从怪兽区进入墓地；长枪龙由表侧攻击变表侧守备 | 已验证 |

长枪龙①在战斗中适用，没有单独的 `effect_activated` 事件。剧本用攻击对象、伤害步骤内的公开攻守值、单次伤害事件和后置 LP 共同验证穿透伤害；不把最终 LP 差额单独当作因果证据。②的转守备是同局附带核查。Guest 在第 2 回合主要阶段 2 投降，仅用于结束测试。场景附有两端实际提交的独立 YDK。

## 回放证据与边界

- 原始录制：`out/duel-recordings/49948629e6ec469b82665f7e5f56fdd6/`；编译 `compiled`、Host 6 步、Guest 3 步、无阻断；自动验证 `validated`。
- 补断言后的单场 HTTP v3 双端无头回放：`out/agent-e2e-runs/1791700491-83761/scenario-report.json`，`passed`、`duel_finished`、双方步骤耗尽。只回放了本候选。
- 收录后仅回放正式路径 `tests/scenarios/spear-dragon-piercing-damage/scenario.yaml`：`out/agent-e2e-runs/1791700610-86465/scenario-report.json`，HTTP v3，`passed`、`duel_finished`、双方步骤耗尽；没有运行其他场景或批量回归。
- 场景断言新增了战斗双方及格子、公开攻守值、单次 LP 伤害值的匹配能力；对应测试为 `agent_sdk/tests/test_scenario.py`，契约见 `docs/contracts/agent-scenario-v1.md`。

本场景未覆盖守备力不低于攻击力、伤害被无效或修正、重放攻击、真实模型、GUI 剧本播放或 Windows。
