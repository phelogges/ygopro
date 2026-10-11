# 「心变」①取得对方怪兽控制权

录制 ID：`45bce9eee6dc42babc429f5b5ec3d600`。本场景经用户审核后收入正式回归集。原始双端 JSONL 和回放诊断数据留在 Git 忽略的 `out/`。

## 对局过程

Host 猜拳获胜并选择先攻。第 1 回合主要阶段，Host 将「火山鼠」（33112041）通常召唤到怪兽区序号 2，然后结束回合。Guest 第 2 回合从手牌发动「心变」（04031928），选择 Host 怪兽区序号 2 的「火山鼠」为对象。效果结算时，它移至 Guest 怪兽区序号 0，控制者变为 Guest。「心变」进入 Guest 墓地。Guest 结束回合；结束阶段它返回 Host 怪兽区序号 0。第 3 回合 Host 投降，权威终局为 Guest 获胜。

## 目标审核

| 可核查目标 | 结论 | 证据与机器断言 |
| --- | --- | --- |
| 发动「心变」①并选择对方怪兽 | 已验证 | Guest 的 `activate` 候选与双端 `effect_activated` 均核对 `card_id=04031928`、`description_id=0`；`select_cards` 候选定位对方怪兽区序号 2，提示快照确认该格是表侧「火山鼠」。候选自身未携带卡片 ID。 |
| 结算后获得控制权 | 已验证 | 双端按本视角分别断言 `card_moved` 从 Host 怪兽区序号 2 移至 Guest 怪兽区序号 0，事件位于连锁处理期间。Guest 下一决策快照和 Host 结束阶段选择位置前的快照均确认原格为空、Guest 格有表侧「火山鼠」且控制者为 Guest。 |
| 结束阶段归还控制权 | 已验证 | 双端分别断言后续 `card_moved` 从 Guest 怪兽区序号 0 移回 Host 怪兽区序号 0；终局前双端快照均确认该卡控制者为 Host。 |
| 可重放至终局 | 已验证 | 原始录制 `manifest.json` 与 `validation-report.json` 均为 `validated`；候选独立回放 `out/agent-e2e-runs/1791695084-76734/scenario-report.json` 和收录后正式路径的单场报告 `out/agent-e2e-runs/1791696756-1291/scenario-report.json` 均为 `passed`、`duel_finished`，双方步骤耗尽。本次按用户要求未运行其他剧本。 |

此处的 `card_moved.reason_flags=16` 仅断言收到的原始位标志，不推导协议未提供的因果。规则上的原持有者 `owner` 在「心变」期间不变，当前控制者 `controller` 按 Host → Guest → Host 变化。客户端 `ClientCard` 有 `owner`，但本次发送给 Agent 的快照没有 `owner`：序列化器只在当前区域收到有效 `QUERY_OWNER` 后才输出它。卡片 `instance_id` 随控制者和格子变化，因此场景凭单只场上目标、双端移动事件和前后快照验证控制权转移与归还，不宣称机器验证了原持有者字段。本局不覆盖目标不合法、效果无效、期间离场、再次变更控制权、真实模型、GUI 场景播放或 Windows。
