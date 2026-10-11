# 「哥布林德伯格」①从手牌特殊召唤怪兽

> 状态：经用户审核并收录的严格场景。来源：人工双客户端录制 `5d35df7a0c28434b83ae9dbd064372b7`，2026-10-11，macOS Debug。

## 测试目标与结论

用户原话及整理目标见 [goal.md](goal.md)。本局实际覆盖两次①效果：Guest 第 1 回合通常召唤「哥布林德伯格」（25259669），从手牌特殊召唤「哥布林暗杀部队」（66707058）；Host 第 2 回合通常召唤另一只「哥布林德伯格」，从手牌特殊召唤「火山鼠」（33112041）。两次处理后，发动效果的「哥布林德伯格」均由表侧攻击表示变为表侧守备表示。目标 **已验证**。

| 核查点 | 双端证据与断言 | 结论 |
| --- | --- | --- |
| Guest ①效果发动 | 双端 `effect_activated` 指向 25259669、`description_id=404154704`，位置为 Guest 怪兽区 1 | 已验证 |
| Guest 手牌怪兽特殊召唤 | 双端观察到 Guest 手牌至怪兽区 3 的 `card_moved`（`reason_flags=2048`）、66707058 的 `special_summon_started` 与 `special_summon_finished`；Guest 手牌减少、怪兽区增加 | 已验证 |
| Guest 哥布林德伯格变守备 | 双端怪兽区 1 的 `position_changed` 为表侧攻击→表侧守备，后置快照也为守备 | 已验证 |
| Host ①效果发动与特殊召唤 | 同样的效果身份指向 Host 怪兽区 2；双端观察到 Host 手牌至怪兽区 1 的移动、33112041 的特殊召唤开始与完成 | 已验证 |
| Host 哥布林德伯格变守备 | 双端怪兽区 2 的 `position_changed` 为表侧攻击→表侧守备，后置快照也为守备 | 已验证 |

候选剧本对两次效果分别写了双端有序事件断言，且每个效果连锁内准确出现一次 `special_summon_started`。特殊召唤目标的身份来自各自的选卡提示和公开的特殊召唤事件；对手隐藏手牌在召唤前没有被补入卡片身份。Host 在第 2 回合主要阶段 2 投降，仅用于结束测试。场景附有双方实际提交的独立 YDK。

## 回放证据与边界

- 原始录制：`out/duel-recordings/5d35df7a0c28434b83ae9dbd064372b7/`；编译 `compiled`、Host 8 步、Guest 7 步、无阻断，自动验证 `validated`。
- 补断言后的单场 HTTP v3 双端无头回放：`out/agent-e2e-runs/1791699447-60771/scenario-report.json`，`passed`、`duel_finished`、双方步骤耗尽。只回放了本候选。
- 收录后仅回放正式路径 `tests/scenarios/goblinbergh-hand-special-summon/scenario.yaml`：`out/agent-e2e-runs/1791699600-64217/scenario-report.json`，HTTP v3，`passed`、`duel_finished`、双方步骤耗尽；未运行其他场景或批量回归。

本场景没有验证效果无效、特殊召唤失败、里侧特殊召唤、其他等级怪兽、真实模型、GUI 剧本播放或 Windows。
