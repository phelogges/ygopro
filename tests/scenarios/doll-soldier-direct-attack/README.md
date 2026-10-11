# 「人偶兵卒」①直接攻击

> 状态：已由用户审核收录。用户原话与可核查目标见 [goal.md](goal.md)。

## 录制与场景

- 人工双客户端录制 ID：`8c3c44951f82458c835ad48ae30ca1ec`。双端原始 JSONL、清单、编译报告及时间线留在本机 `out/duel-recordings/8c3c44951f82458c835ad48ae30ca1ec/`，不纳入 Git。
- 房间为单局 1v1，不洗牌、起手五张、双方 LP 8000、每回合抽一张且无时间限制。实际提交的 Host、Guest 两副 40 张主卡组分别与本目录 `host.ydk`、`guest.ydk` 完全一致。
- 编译结果 `compiled`：Host 3 步、Guest 9 步，无阻断及序号歧义；录制器自动回放 `validated`。Host 第 1 回合通常召唤「人偶兵卒」至怪兽区 3，Guest 第 2 回合也通常召唤「人偶兵卒」至怪兽区 3。

## 目标核查

| 目标 | 结论 | 双端可见证据及断言 |
| --- | --- | --- |
| 对手有怪兽时①仍允许直接攻击 | 已验证 | Guest 战斗开始时，双方怪兽区各有一只表侧攻击表示的「人偶兵卒」。Guest 的 `battle_command` 攻击候选为本方怪兽区 3，`direct_attackable: true`。首次选攻击后，Guest 在 `description_id: 31`（`strings.conf` 为“是否直接攻击？”）选择拒绝，再取消选择对手怪兽；第二次选攻击后接受直接攻击。 |
| 实际攻击目标为对手玩家 | 已验证 | 双端各自观察到一次 `attack_declared`：攻击者是 Guest 怪兽区 3，`target_player` 为 Host，`target_location: 0`，没有目标怪兽序号。两端在伤害步骤中均观察到 `battle_values_observed` 的攻击力 800、目标区域 0；战斗前后 Host 怪兽区 3 的怪兽仍在场。 |
| 对手承受 800 点战斗伤害 | 已验证 | `life_points_damaged` 指向 Host，`value: 800`。Guest 从攻击宣言到伤害步骤结束的区间，及 Host 相同区间内，该受伤方伤害事件均恰好一次；Guest 的下一个战斗阶段决策快照显示 Host LP 7200，双方终局 LP 对应 7200/8000。 |

①为允许直接攻击的持续效果，不要求单独的 `effect_activated`。首次尝试被取消，没有产生攻击宣言或伤害；剧本保留了这段人工操作。Host 在 Guest 进入主要阶段 2 后投降，仅用于取得权威终局，不用投降推断伤害。②检索「升变」不在本局测试目标内。

## 验证与边界

```bash
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/doll-soldier-direct-attack/scenario.yaml
```

2026-10-11 候选单场回放报告 `out/agent-e2e-runs/1791708527-15417/scenario-report.json` 为 HTTP v3、`passed`、`duel_finished`，Host/Guest 剩余步骤均为 0。收录后的正式路径报告 `out/agent-e2e-runs/1791708702-19299/scenario-report.json` 同样为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽；本次未运行其他十八个场景或十九场景批量回归。回放通过证明已写入的双端动作、事件和后置状态断言成立。本局不覆盖直接攻击被无效、攻击力修改、伤害减免、②效果、真实模型、GUI 场景播放或 Windows。
