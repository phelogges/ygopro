# 「神机王 乌尔」①逐只攻击与②战斗伤害归零

> 状态：已由用户审核收录。目标原话和整理见 [goal.md](goal.md)。

## 录制与场景

- 人工双客户端录制 ID：`08b2c00d604848aaa60987a3705d7159`。原始双端 JSONL、清单、编译报告和时间线在 `out/duel-recordings/08b2c00d604848aaa60987a3705d7159/`，不纳入 Git。
- 单局 1v1，双方不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。实际提交的两副 40 张主卡组与本目录 `host.ydk`、`guest.ydk` 逐项一致。编译结果为 `compiled`，Host 9 步、Guest 6 步，无阻断；编译器自动回放为 `validated`。
- Guest 第 1 回合通常召唤「火山鼠」到怪兽区 0；Host 第 2 回合通常召唤「神机王 乌尔」到怪兽区 0；Guest 第 3 回合通常召唤另一只「神机王 乌尔」到怪兽区 2。Host 第 4 回合进入战斗阶段。

## 目标核查

| 目标 | 结论 | 双端可见证据与机器断言 |
| --- | --- | --- |
| ①同一只乌尔向对方全部怪兽各作一次攻击 | 已验证本局的两只怪兽 | 同一攻击方怪兽区 0 先攻击 Guest 怪兽区 0「火山鼠」，首次伤害步骤后仍在场，再攻击 Guest 怪兽区 2 的另一只乌尔。两次 `attack_declared` 的攻击者格子相同、对象格子不同；首次目标战斗破坏入墓，第二次双方乌尔战斗破坏入墓。攻击前快照显示 Guest 只有这两只怪兽。 |
| ②乌尔战斗时对方战斗伤害为 0 | 已验证第一战；第二战只作一致性检查 | 第一战 `battle_values_observed` 为 1600 攻击力对 500 攻击力、双方怪兽均表侧攻击表示，通常应对 Guest 造成 1100 点战斗伤害。Host、Guest 各自事件流中，从该次 `attack_declared` 到 `damage_step_ended` 的对方 LP 伤害事件均为 0；两次攻击前后的 Host 快照和双端终局 LP 均为 8000/8000。第二战是 1600 对 1600，本来就不会造成 LP 伤害，因此不作为②的独立证明。 |

场景在双端分别断言攻击对象、战斗数值、战斗破坏移动、两次伤害步骤结束，并对**每一次**攻击的区间分别断言对手 `life_points_damaged` 次数为 0。Guest 在 Host 进入主要阶段 2 后投降，仅用于产生权威终局；没有把终局 LP 单独当成②效果的证据。①②为战斗中适用的效果，本局不要求 `effect_activated` 事件。

## 验证与边界

本场景单场命令：

```bash
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/machine-king-ur-all-monsters-zero-damage/scenario.yaml
```

2026-10-11 候选报告 `out/agent-e2e-runs/1791701403-4010/scenario-report.json`：Agent HTTP v3、`passed`、`duel_finished`，Host/Guest 剩余步骤均为 0。收录后正式路径报告 `out/agent-e2e-runs/1791701681-10150/scenario-report.json` 也为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽；此次只运行本场景，未运行其他已入库场景或十八场景批量回归。

本局没有覆盖对三只以上怪兽的连续攻击、再次攻击已存活目标、攻击被无效或重放、伤害修正叠加、真实模型、GUI 场景播放或 Windows。第二次与同攻击力乌尔的战斗不能独立证明②效果。
