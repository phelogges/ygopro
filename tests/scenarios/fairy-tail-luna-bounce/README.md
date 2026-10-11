# 「妖精传姬-辉夜」②返回手牌与同名卡无效分支

录制 ID：`85475b5b1e3a400e8f398c4b94c1eea5`。本场景经用户审核后收入正式回归集。原始双端 JSONL 和回放诊断数据留在 Git 忽略的 `out/`。

## 对局过程

Guest 猜拳获胜并选择先攻，第 1 回合通常召唤「妖精传姬-辉夜」（86937530）。第 2 回合 Host 通常召唤「火山鼠」（33112041）后，Guest 连锁发动辉夜②，以该怪兽为对象。Host 在“是否从卡组或额外卡组送同名卡”的选择中选“否”（`description_id=1214`）；结算时「火山鼠」返回 Host 手牌，辉夜返回 Guest 手牌，双方手牌发生洗切。

第 3 回合 Guest 通常召唤「地狱亡灵」（40575313）。第 4 回合 Host 通常召唤辉夜并发动②，以「地狱亡灵」为对象；Guest 这次选“是”（`description_id=1213`），从卡组送一张同名卡去墓地。该连锁项失效，场上的辉夜与对象怪兽都没有回手牌。Guest 随后投降，权威终局为 Host 获胜。

## 目标审核

| 可核查目标 | 结论 | 证据与机器断言 |
| --- | --- | --- |
| 第一次发动辉夜②并选择对方怪兽 | 已验证 | Guest 的 `activate` 选择及双端 `effect_activated` 断言核对辉夜 ID、②效果 `description_id=1391000481` 和连锁序号；`select_cards` 定位 Host 怪兽区序号 0，提示快照确认表侧「火山鼠」。 |
| 对方未送同名卡，双方怪兽回手牌 | 已验证 | Host 选择 `option description_id=1214`（`strings.conf` 对应“否”）；双端各自按本视角断言「火山鼠」与辉夜从怪兽区移至各自手牌，效果发动至连锁结束之间 `card_moved(to_location=2)` 恰好两次。Host 后续本方手牌中「火山鼠」增加一张；Guest 后续本方手牌中有辉夜，双方怪兽区均为空。对方手牌身份只用数量断言。 |
| 第二次送同名卡使效果无效，没有弹回 | 已验证，属于录制后补充覆盖 | Guest 选择 `option description_id=1213`（“是”）并从卡组选择 40575313；双端断言卡组到墓地移动及 `chain_link_disabled`，该连锁区间内到手牌移动次数为零；终局前辉夜和目标怪兽都留场。 |
| 对局可回放至终局 | 已验证 | 原始录制 `manifest.json` 与 `validation-report.json` 均为 `validated`；候选独立回放 `out/agent-e2e-runs/1791697320-13696/scenario-report.json` 和收录后正式路径的单场报告 `out/agent-e2e-runs/1791697496-17596/scenario-report.json` 均为 `passed`、`duel_finished`，双方步骤耗尽。本次按用户要求未运行其他剧本。 |

手牌洗切由 `allowed_random_events: [hand_shuffle]` 显式允许；场景按卡片 ID 与数量匹配，不依赖洗切后的手牌顺序，也未混入掷骰或抛币结果。本场景不覆盖额外卡组怪兽返回额外卡组、无同名卡时的提示差异、目标离场、真实模型、GUI 场景播放或 Windows。
