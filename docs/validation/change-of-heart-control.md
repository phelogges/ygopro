# 「心变」①控制权转移与归还录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/change-of-heart-control/`](../../tests/scenarios/change-of-heart-control/README.md)。现行场景格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `45bce9eee6dc42babc429f5b5ec3d600` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张和无限时设置。双端日志、实际提交的 YDK 与编译报告完整；自动编译 Host 4 步、Guest 5 步，原始无头验证状态 `validated`。Host 在第 3 回合投降，双方权威终局一致，Guest 获胜。

Guest 发动 04031928 的①效果并选择 Host 怪兽区序号 2 的表侧 33112041。双方各自收到该效果的发动和连锁处理事件。结算时，Host 视角的 `card_moved` #23 从本方怪兽区序号 2 指向对方怪兽区序号 0；Guest 视角的 #26 从对方序号 2 指向本方序号 0。Guest 录制快照 #300、Host #293 均看到怪兽改由 Guest 控制。Guest 结束回合后，Host 的 `card_moved` #30 与 Guest 的 #31 各自记录反向移动；Host 快照 #376、Guest #377 以及后续终局前快照看到控制者恢复为 Host。场景分别在双端断言两次跨控制者移动、连锁顺序、取得后的场面与归还后的场面。

补断言后的独立 HTTP v3 双端无头回放报告 `out/agent-e2e-runs/1791695084-76734/scenario-report.json` 为 `passed`、`duel_finished`，双方步骤耗尽。用户确认收录后，仅对正式路径 `tests/scenarios/change-of-heart-control/scenario.yaml` 执行单场验收；报告 `out/agent-e2e-runs/1791696756-1291/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽。本次未运行其他十一个剧本或十二场景批量回归。目标选择候选本身不带卡片 ID，但该提示的公开快照标明目标格的「火山鼠」身份。规则上的原持有者 `owner` 不因「心变」改变；本次 Agent 快照缺少 `owner` 是因为客户端序列化器要求当前区域有有效的 `QUERY_OWNER` 观察，不表示客户端类没有该字段。本场景验证当前控制者 `controller` 的 Host → Guest → Host 变化，不宣称机器验证了原持有者字段。此证据不覆盖效果无效、目标不合法、期间离场、重叠控制权效果、真实模型、GUI 场景播放或 Windows。
