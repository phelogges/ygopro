# 天杯龙白龙从卡组盖放场地魔法

## 测试目的与来源

以固定牌序验证「天杯龙 白龙」（`39931513`）①效果从卡组选择「杯满的灿幻庄」（`30336082`）并盖放到场地区域。分别检查 Host 的动作与盖卡、Guest 收到的公开展示事件及其仍然隐藏身份的当前快照。本场景验证协议观测和动作回放，不验证模型的战术选择。

人工双客户端录制：`out/duel-recordings/5da8960aff234c089e3d576bfde4cf7e/`。`manifest.json` 与 `validation-report.json` 均为 `validated`；实际提交的两副牌已复制为本目录的 `host.ydk` 和 `guest.ydk`。房间为单局 1v1、起手 5 张、LP 8000、每回合抽 1 张、无时间限制，已启用「不洗牌」；未启用「不检查卡组」，不影响本次确定性回放。

Host 先攻，通常召唤天杯龙白龙，发动①效果，从卡组选择杯满的灿幻庄并选择盖放。Host 结束回合后，Guest 在第二回合投降，Host 获胜。编译器生成 Host 6 步、Guest 0 步，无同形候选序号覆盖。

## 目标审核

| 目标 | 状态 | 证据与边界 |
| --- | --- | --- |
| 固定起手，发动天杯龙白龙①效果并选择盖放分支 | 已验证 | `scenario.yaml` 的 Host 6 步包含通常召唤、发动效果、从卡组选择 `30336082`、选择盖放选项；实际牌组及回放步骤均吻合。 |
| `30336082` 盖放在 Host 场地区域 | 已验证 | Host 的当前快照在 `spell` 大区序号 5 有 `known=true`、里侧的 `30336082`；终局断言检查同一位置。 |
| Guest 观察到盖放和公开展示，但当前仍不可查看盖卡身份 | 已验证 | 原始 Guest 日志的 `MSG_SET` 快照 #164、`MSG_CONFIRM_CARDS` 快照 #166 显示序号 5 的盖卡仍为 `known=false`。回放的 Guest 事件 `card_set` #16 与 `cards_revealed` #17 都含 `location=8, sequence=5`；后者含 `card_id=30336082`。场景直接断言展示事件和 Guest 终局里侧场地区位置。 |
| 双端一致终局及独立回放 | 已验证 | 双方都收到 Host 获胜的权威终局；增强事件断言后的独立回放为 `passed`，双方剧本步骤耗尽。 |
| Agent 在实战中写入并使用场地区推断笔记 | 未验证 | 该回放不调用 LLM。现有 `zone="spell"` 笔记可容纳场地区的自然语言推断，但没有独立的 `zone="field"` 工具和记录；见下文。 |

## 验证

```sh
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/tenpai-field-set/scenario.yaml --timeout 120
```

正式路径的增强事件断言回放报告：`out/agent-e2e-runs/1791563079-41425/scenario-report.json`，状态 `passed`，终局 `duel_finished`，赢家 Host，双方剩余步骤均为 0。原始双端 JSONL 和诊断报告保存在 Git 忽略目录，不收入场景包。

## 场地区笔记能力与限制

当前客户端把场地区表示为 `spell` 大区序号 5，而不是单独的 `field` 区域。Guest 可以通过 `zone_state(player=1, zone="spell")` 或完整场面读取到序号 5 的里侧卡位，但当前快照不会给出其 ID；历史 `cards_revealed` 事件才给出已公开的 ID 和位置。

现有 `write_zone_note(player=1, zone="spell", ...)` 可以引用 Guest 本视角 `card_set`、`cards_revealed` 的真实事件 ID，写下“对手场地区序号 5 曾展示为杯满的灿幻庄”；`read_zone_note(player=1, zone="spell")` 能读回。用本场景同形事件做独立存储测试已验证该读写路径。`zone="field"` 当前返回 `invalid_note`，没有独立的场地区笔记、模型输入字段或网页分栏。现有魔陷区笔记是一段自由文本，程序不会自动把场地区推断分离、更新或判定失效；真实模型是否主动写入仍需实战验证。

未来扩展独立场地区笔记时，应使用本次录制验证的序号 5 事件，另外录制盖卡离位、场地区替换等情况，以决定模型何时复核笔记。Windows 回放未验证。本场景经用户审核后收入 `tests/scenarios/`。
