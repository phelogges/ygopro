# 黑魔女从卡组盖放「原罪宝－蛇眼」

## 测试目的

以固定牌序验证「黑魔女 迪亚贝尔斯塔尔」（`72270339`）②效果从卡组选择「原罪宝－蛇眼」（`89023486`），在 Host 的魔法与陷阱区域盖放；检查 Host 的决策提示，以及双方各自收到的公开展示事件和场面状态。场景只测试协议观测与动作回放，不证明 Agent 的战术选择。

## 来源与关键交互

- 人工双客户端录制：`out/duel-recordings/6aba04db61ae42fc8301a5165b60bb75/`，`manifest.json` 状态为 `validated`。双方实际提交的牌组复制为本目录的 `host.ydk`、`guest.ydk`。
- 房间为单局 1v1、起手 5 张、LP 8000、每回合抽 1 张、无时间限制、`no_shuffle_deck=true`。实际 `no_check_deck=false`；录制前建议勾选「不检查卡组」，但该选项不是本场景确定性的必要条件，本次录制与回放均通过。
- Host 先攻，以「火山鼠」（`33112041`）作送墓代价特殊召唤黑魔女；发动②效果，从卡组选择 `89023486`，盖放到魔陷区序号 3。Host 结束回合，第二回合 Host 投降，Guest 获胜。
- 编译报告：Host 8 个决策步骤、Guest 0 个；其中一次同名「火山鼠」选择使用录制时的候选序号，回放已核对。

## 目标审核

| 目标 | 状态 | 证据与边界 |
| --- | --- | --- |
| 固定起手和黑魔女②效果的合法动作链 | 已验证 | `scenario.yaml` 的 Host 8 步、实际提交的 YDK，以及回放报告中的双方起手和步骤耗尽。 |
| 从卡组盖放 `89023486` 到 Host 魔陷区序号 3 | 已验证 | Host 的 `select_cards` 和 `select_place`，盖放后的 Host 可见快照与终局断言，单张牌的 `card_set`、`cards_revealed` 事件断言。 |
| Guest 获知展示卡的 ID，同时盖卡快照仍保密 | 已验证 | 原始 `guest.jsonl` 的入站消息 #167 为 `MSG_SET`、#169 为 `MSG_CONFIRM_CARDS`；剧本断言 Guest 的 `card_set`、`cards_revealed` 事件和序号 3 的里侧盖卡。最终报告中 Guest 快照的该卡为 `known=false`，不含卡片 ID。 |
| 客户端发送“展示的 `89023486` 对应序号 3 盖卡”的精确关联 | 已验证 | 最终回放报告的 Guest 事件 #15 `card_set` 与 #16 `cards_revealed` 均含 `sequence=3`，后者同时含 `card_id=89023486`；场景直接断言了该序号。此前认为展示事件缺少序号的分析有误。此项验证的是协议观测，未验证真实模型是否会使用该信息写笔记。 |
| 双端完整终局和重放 | 已验证 | 双方均收到一致终局，Host 投降，Guest 获胜；录制自动回放及增加事件断言后的独立回放均通过。 |

## 验证

```sh
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/snake-eye-deck-set/scenario.yaml --timeout 120
```

本场景增加了双方 `card_set`、`cards_revealed` 事件断言，后者直接检查公开展示的格子序号；同时补了 Guest 里侧盖卡序号断言。正式路径的独立回放报告：`out/agent-e2e-runs/1791560888-2716/scenario-report.json`，状态 `passed`，终局 `duel_finished`，赢家 Guest，双方步骤均耗尽。

## 范围与尚未验证

当前客户端已把 `MSG_CONFIRM_CARDS` 明确展示的魔陷区格子序号写入 `cards_revealed`，仍在 Guest 当前快照隐藏卡片 ID。本次补充了场景格式对该序号的断言；另在 Agent 服务端提供了对手魔陷区的独立推断笔记工具。**本剧本回放不调用 LLM，也不测试模型主动写笔记**；该工具由服务端测试验证，真实模型使用情况仍待实战观察。位置复用后需要 Agent 根据新事件修订笔记，程序不把推断写回权威快照。Windows 回放未验证。

原始双端 JSONL 只保存在忽略目录，不进入版本控制。本场景经用户审核后收入 `tests/scenarios/`。
