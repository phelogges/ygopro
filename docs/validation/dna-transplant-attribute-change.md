# 「DNA移植手术」属性变化录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [测试集](../../tests/scenarios/dna-transplant-attribute-change/README.md)。现行协议见 [HTTP v3](../contracts/agent-http-v3.md)，事件字段见其继承的 [状态契约](../contracts/agent-http-v2.md)，断言见 [严格场景](../contracts/agent-scenario-v1.md)。

人工双端录制 `8c4fc7dd343f4a909bb611977cab2995` 为不洗牌的单局 1v1。双端日志完整，编译报告为 `compiled`（Host 10 步、Guest 8 步、无阻断），录制清单为 `validated`；候选两份 YDK 与录制草稿逐字节一致，双方各 40 张主卡组。

Host 场上「地狱亡灵」初始暗属性 `32`，Guest 场上「火山鼠」初始炎属性 `4`。Host 发动「DNA移植手术」宣言神 `64` 后，两只表侧怪兽都显示 `64`；Guest 发动另一张同名陷阱宣言风 `8` 后，两只都显示 `8`。录制的两端可见快照覆盖初始、神、风三个状态；Host 投降仅用于使回放进入权威终局。

录制暴露出原 Agent 事件历史遗漏属性更新：旧客户端把 `MSG_UPDATE_DATA` 作为无需事件的包，决策快照之间的神属性在 Host 历史中消失，Guest 终局服务镜像仍停在神属性。修复后复用可见卡序列化，在原生客户端观察到同格同已知表侧卡的数值变化时生成通用 `card_value_changed`；两端 Agent 历史均依次保存暗／炎→神与神→风，每端四条 `field: attribute` 事件。事件不带卡片身份或效果归因；`/v3/sync` 不刷新权威快照，因此终局镜像仍须结合事件截止点阅读。

场景在宣言前、两次宣言后以及双端终局断言快照，另在双端 Agent 历史中断言两次陷阱发动与四次属性变化的顺序。macOS Debug CMake 构建通过；Python 场景测试 36 项和状态测试 21 项通过，Ruff 与 Pyright 通过。候选的 HTTP v3 回放报告 `out/agent-e2e-runs/1791711041-70648/scenario-report.json` 与用户确认收录后的正式路径报告 `out/agent-e2e-runs/1791711836-88148/scenario-report.json` 均为 `passed`、`duel_finished`，Guest 胜，Host/Guest 剩余步骤均为 0。本次未运行其他剧本或批量回归；未验证真实模型、GUI 场景播放、Windows 以及陷阱离场后的属性恢复。
