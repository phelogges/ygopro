# 「神机王 乌尔」逐只攻击与战斗伤害归零录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/machine-king-ur-all-monsters-zero-damage/`](../../tests/scenarios/machine-king-ur-all-monsters-zero-damage/README.md)。现行格式以[严格场景契约](../contracts/agent-scenario-v1.md)为准。

人工双客户端录制 `08b2c00d604848aaa60987a3705d7159` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。双端 JSONL 完整，实际提交的 40 张主卡组与收录的 YDK 一致。编译为 `compiled`（Host 9 步、Guest 6 步、无阻断），录制器自动回放为 `validated`。

Host 第 4 回合，表侧攻击的「神机王 乌尔」从怪兽区 0 依次攻击 Guest 怪兽区 0 的「火山鼠」与怪兽区 2 的另一只乌尔。首次战斗数值为 1600 对 500，火山鼠战斗破坏入墓；首次攻击后 Host 乌尔仍在场并可再次宣言攻击。第二次为 1600 对 1600，双方乌尔均战斗破坏入墓。双端分别观察到攻击对象、数值、移动及伤害步骤结束。

场景对两次攻击各写有双端有序事件断言与区间计数断言：每次从 `attack_declared` 到 `damage_step_ended`，对手的 `life_points_damaged` 次数为 0。Host 两次战斗前后的决策快照及双方终局 LP 均为 8000/8000。第一战若无②效果，表侧攻击 1600 对 500 通常应造成 1100 点战斗伤害，因此零伤害支持②效果；第二战同攻击力，零伤害不足以独立证明②。

补断言后仅运行本候选场景，报告 `out/agent-e2e-runs/1791701403-4010/scenario-report.json` 显示 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/machine-king-ur-all-monsters-zero-damage/scenario.yaml`，报告 `out/agent-e2e-runs/1791701681-10150/scenario-report.json` 同样为 HTTP v3、`passed`、`duel_finished`，双端步骤耗尽。Guest 在主要阶段 2 投降作为终局。未运行其他十七个已入库场景或十八场景批量回归；尚未验证三只以上目标、攻击无效或重放、其他伤害修正、真实模型、GUI 场景播放和 Windows。
