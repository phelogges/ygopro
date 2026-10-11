# 「天岩户」②结束阶段返回手牌

> 状态：经用户审核并收录的严格场景。来源：人工双客户端录制 `692912dd28f24581a7a2d855affebe51`，2026-10-11，macOS Debug。

## 测试目标与结论

用户原话及整理目标见 [goal.md](goal.md)。本次验证 Guest 第 1 回合通常召唤「天岩户」（32181268），在同一回合结束阶段发动②效果并返回 Guest 手牌。目标 **已验证**。

| 核查点 | 可审核证据 | 结论 |
| --- | --- | --- |
| 召唤后留场直到结束阶段 | Guest 在 `main_1` 通常召唤至怪兽区 1；结束回合的决策快照和结束阶段强制连锁提示仍显示该卡表侧在场 | 已验证 |
| ②效果在结束阶段发动 | Guest 的 `chain` 提示位于第 1 回合 `end`，唯一候选为 `card_id=32181268`、`description_id=1104`、`forced=true`；双端事件为效果发动、连锁加入、开始处理 | 已验证 |
| 结算时返回手牌 | 双端事件均有怪兽区 1 到 Guest 手牌的一次 `card_moved`，`reason_flags=64`；Guest 手牌重新出现 32181268，怪兽区为空 | 已验证 |
| 对手视角不泄露隐藏身份 | Host 的对手手牌快照由 4 张变 5 张，卡片列表不含隐藏卡 ID；公开的效果发动事件仍显示 32181268 | 已验证 |

`scenario.yaml` 包含双端按序事件、连锁内恰好一次怪兽区至手牌移动计数，以及后置区域断言。Host 在第 2 回合主要阶段投降，仅用于结束测试；不作为效果成功的依据。两端卡组是录制时实际提交的独立副本。

## 回放证据

- 原始录制的编译报告：`out/duel-recordings/692912dd28f24581a7a2d855affebe51/draft/compile-report.json`，状态 `compiled`，Host 0 步、Guest 4 步、无阻断。
- 自动原始验证：同一录制目录下 `validation-report.json`，状态 `validated`。
- 补强断言后的单场回放：`out/agent-e2e-runs/1791697994-28556/scenario-report.json`，HTTP v3，`passed`、`duel_finished`、双方步骤耗尽。
- 收录后仅回放正式路径 `tests/scenarios/amanowato-end-phase-return/scenario.yaml`：`out/agent-e2e-runs/1791698242-34003/scenario-report.json`，HTTP v3，`passed`、`duel_finished`、双方步骤耗尽；没有运行其他场景或批量回归。

仅验证了此局同一控制者兼原持有者的返回手牌。没有覆盖控制权改变后返回原持有者、效果无效、真实模型决策、GUI 场景播放或 Windows。`hand_shuffle` 已显式允许，因此不依赖回手后的手牌序号。
