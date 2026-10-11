# 河马狂欢节①三只衍生物录制与回放

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/hippo-carnival-three-tokens/`](../../tests/scenarios/hippo-carnival-three-tokens/README.md)。现行场景格式见[固定场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `bc22d29e7ba9495f9ed526e27ceb0f6b` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张和无限时设置。双端日志、实际提交的两副 YDK 和编译报告完整。草稿包含 Host 3 个、Guest 11 个决策步骤；原始自动验证状态 `validated`。Host 在第 2 回合投降，权威终局为 Guest 获胜。

Guest 发动 18027138 后，双方各自收到同一连锁的 `effect_activated`、`chain_link_solving`，以及 18027139、18027140、18027141 的三次 `special_summon_started`，位置分别为己方／对方怪兽区序号 0、3、4；之后收到 `special_summon_finished` 和 `chain_link_solved`。Guest 下一决策与 Host 后续快照都显示三只衍生物留场。场景新增双端有序事件断言及区间计数断言，要求从该效果发动至连锁处理完成之间恰好三次特殊召唤开始事件。场景解析器仅扩展本地测试断言，使 `special_summon_started` 可按客户端实际收到的卡片 ID 和格子匹配；客户端与 Agent 的协议字段未改。

补断言后的 HTTP v3 双端无头回放报告 `out/agent-e2e-runs/1791692340-16360/scenario-report.json` 为 `passed`、`duel_finished`，双方步骤耗尽。场景单元测试 33 项通过。该证据验证本局三只衍生物的召唤和最终场面；不能证明不能解放、额外卡组特殊召唤限制或攻击对象限制，也不覆盖真实模型、GUI 场景播放与 Windows。

经用户审核收录后，运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir`；汇总报告 `out/agent-e2e-runs/batch-1791692520-20370/batch-report.json` 为 `total: 10`、`passed: 10`、`failed: 0`、`unsupported: 0`。本场景对应 `scenario-004.json`，状态 `passed`。其中随机的魔术礼帽场景按自身采样目标运行；批量通过不表示所有隐藏排列已覆盖。
