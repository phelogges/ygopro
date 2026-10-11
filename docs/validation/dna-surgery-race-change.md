# 「DNA改造手术」种族变化录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [测试集](../../tests/scenarios/dna-surgery-race-change/README.md)。现行格式见 [严格场景契约](../contracts/agent-scenario-v1.md)，通用数值事件见 [HTTP 状态契约](../contracts/agent-http-v2.md)。

人工双客户端录制 `392b315dd51a4239a801e3d480de8250` 为不洗牌的单局 1v1。双端日志完整，房间参数合规；清单及自动回放为 `validated`，编译报告 `compiled`（Host 24 步、Guest 14 步，无阻断）。实际提交的双方主卡组各 40 张，无额外或备牌。原始双端 JSONL 与诊断报告留在本机忽略目录。

Host 的表侧「火山鼠」原种族为 `128`，Guest 的表侧「地狱亡灵」为 `16`。Host 发动「DNA改造手术」宣言 `33554432` 后，两只怪兽都显示该值；Guest 随后发动自己的同名陷阱宣言 `16777216` 后，两只都显示新值。两端原生可见快照覆盖原值、第一次宣言后的中间值和终值；两端 Agent 已接受历史分别有四条 `card_value_changed(field: race)`，还各有两次同名陷阱发动事件。候选剧本逐端断言事件顺序和三个阶段的可见状态；Guest 投降仅用于进入权威终局。

候选首次加载发现场景断言器允许 `attribute`，却未允许从已有快照读取 `race`。补上 `race` 断言、单元测试及契约说明后，macOS 场景测试 36 项与 Ruff 通过。候选 HTTP v3 回放报告 `out/agent-e2e-runs/1791712425-1376/scenario-report.json` 与用户确认收录后的正式路径报告 `out/agent-e2e-runs/1791712595-5172/scenario-report.json` 均为 `passed`、`duel_finished`，Host 胜，Host/Guest 剩余步骤均为 0。收录后仅运行本场景，未运行其他剧本或批量回归；未验证新怪兽入场、陷阱离场恢复、真实模型、GUI 场景播放与 Windows。
