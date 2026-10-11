# 「天岩户」②结束阶段回手录制验证

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/amanowato-end-phase-return/`](../../tests/scenarios/amanowato-end-phase-return/README.md)。现行格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `692912dd28f24581a7a2d855affebe51` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张、无时间限制。双方实际提交 YDK 和完整 JSONL 保存在本机忽略目录。编译报告为 `compiled`，Host 0 步、Guest 4 步、无阻断；录制器自动验证为 `validated`。

Guest 在第 1 回合主要阶段通常召唤 32181268「天岩户」至怪兽区 1，并直接结束回合。第 1 回合结束阶段，Guest 收到不可取消的 `chain` 提示，唯一候选是该卡 `description_id=1104` 的强制发动。双方可见事件随后依次包含 `effect_activated`、连锁项加入和处理、怪兽区至 Guest 手牌的 `card_moved`（`reason_flags=64`）、连锁处理完成。候选场景分别断言该顺序及连锁内该方向的移动恰好一次。

回手前 Guest 本方手牌为 4 张、怪兽区有表侧天岩户；回手后本方手牌为 5 张并包含 32181268、怪兽区为空。Host 对手手牌数从 4 增至 5，怪兽区从 1 减至 0，但隐藏手牌快照没有卡片 ID。效果发动时卡片身份是公开事件，不能把之后隐藏手牌的身份填入 Host 快照。

补断言后仅对这条候选执行独立 HTTP v3 无头回放，报告 `out/agent-e2e-runs/1791697994-28556/scenario-report.json` 为 `passed`、`duel_finished`，双端步骤耗尽。用户确认收录后，仅回放正式路径 `tests/scenarios/amanowato-end-phase-return/scenario.yaml`，报告 `out/agent-e2e-runs/1791698242-34003/scenario-report.json` 同样为 `passed`、`duel_finished`，双端步骤耗尽；本次未运行其他十三个场景或十四场景批量回归。Host 在第 2 回合主要阶段投降，仅负责终局。场景包包括目标、双份卡组、剧本与审核说明；原始 JSONL 不入 Git。此证据不覆盖变更控制权后按原持有者回手、效果无效、真实模型、GUI 场景播放或 Windows。
