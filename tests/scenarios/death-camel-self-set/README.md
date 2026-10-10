# 死亡骆驼将自身变为里侧守备表示

## 测试目的与来源

以固定牌序验证「死亡骆驼」（卡片密码 `02326738`，协议数值 ID `2326738`）发动①效果，从表侧攻击变为同一怪兽区格子的里侧守备表示。重点检查观察方是否先看到卡片身份，随后收到足以追踪这个位置变化的事件，而当前快照仍隐藏其身份。剧本验证协议观测和动作回放，不测试模型实际决策或写笔记。

人工双客户端录制：`out/duel-recordings/62e7b8fbe66b4bccab6db404a9b3c117/`。清单和自动验证报告均为 `validated`；本目录的两副 YDK 是实际提交牌组的独立副本。房间为单局 1v1、起手 5 张、LP 8000、每回合抽 1 张、无时间限制，开启「不洗牌」，未开启「不检查卡组」。

实际由 Guest 猜拳获胜并先攻，使用 `guest.ydk` 召唤死亡骆驼、发动①效果。Host 在第二回合投降，Guest 获胜。录制编译得到 Guest 4 个决策步骤、Host 0 个，无同形候选序号覆盖。Host/Guest 始终是客户端角色，不随猜拳结果改变。

## 目标审核

| 目标 | 状态 | 证据与边界 |
| --- | --- | --- |
| Guest 起手、召唤并发动死亡骆驼①效果 | 已验证 | `scenario.yaml` 的 Guest 4 步包含起手 ID、通常召唤、效果发动和结算后里侧守备表示。 |
| Host 变更前确实知道卡片身份 | 已验证 | 原始 `host.jsonl` 可见快照 #104：对手怪兽区序号 0 为表侧攻击的 `2326738`，`known=true`。新版客户端回放中 Host 的 `effect_activated` #10 含 `card_id=2326738`、`controller=1`、`location=4`、`sequence=0`；事件断言锁定该公开效果身份和格子。 |
| 双方观察到同一格子从表侧攻击变为里侧守备 | 已验证 | Host 的 `position_changed` #13 和 Guest 的 #15 均为怪兽区 `location=4, sequence=0`，`face_up_attack -> face_down_defense`；场景在两端分别断言。该事件自身没有卡片 ID。 |
| Host 当前快照重新隐藏卡片身份，Guest 仍知道自己的卡 | 已验证 | 原始 Host 快照 #170 和候选回放终局：序号 0 为 `face_down_defense, known=false`，无 `card_id`；Guest 快照为 `known=true, card_id=2326738`。终局双端断言包含 `known`。 |
| 双端权威终局与独立回放 | 已验证 | 双方均收到 Guest 获胜；增强断言后的回放为 `passed`，步骤均耗尽。 |
| Agent 能用专属怪兽区笔记记录此推断 | 工具已验证；真实模型未验证 | `write_zone_note(player=1, zone="main_monster", sequence=0, ...)` 可引用本视角事件写入独立笔记；`read_zone_note`、Pydantic AI、Codex MCP、持久化与只读网页路径均有离线测试。剧本回放自身不调用模型。 |

## 验证

```sh
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/death-camel-self-set/scenario.yaml --timeout 120
```

正式路径回放报告为 `out/agent-e2e-runs/1791600385-66953/scenario-report.json`：`passed`，`duel_finished`，赢家 Guest，Host 和 Guest 剩余步骤均为 0。场上 `effect_activated` 新增本方可见 `sequence=0`，两端事件断言直接检查该序号。

## 笔记工具评估与限制

Host 的事件流有“死亡骆驼在序号 0 发动效果”的公开 ID，随后有同格的表示变化；此外 Host 在变化前的快照明确见过同一格的死亡骆驼。因此 Agent 可以合理记录“对手怪兽区序号 0 的里侧卡曾是死亡骆驼”，但这应是有证据的历史推断，不应写入当前权威快照的 `card_id`。该卡离位、重新盖放或格子被复用后，笔记必须重审。`position_changed` 本身不含 ID，不能仅凭该事件识别任意里侧怪兽。

笔记工具使用 `zone="main_monster", sequence=0..4`，与额外怪兽区区分：当前 `monster` 快照大区仍同时覆盖主怪兽区序号 0–4 与额外怪兽区序号 5–6。五格笔记分别持久保存、进入模型输入并在网页显示；`zone="monster"` 仍非法。Windows 回放和真实模型主动写入尚未验证。

原始双端 JSONL 和诊断文件保存在 Git 忽略目录；本目录经用户审核后收入 `tests/scenarios/`。
