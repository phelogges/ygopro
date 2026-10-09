# 复杂双端决斗展开

- 类型：严格场景（schema v1）；原始人工剧本与事后整理目标见 [goal.md](goal.md)。
- 输入：本目录独立的 `host.ydk`、`guest.ydk`。Host 副本补有第二张 `53927851`；Guest 副本固定第二回合抽牌，原因见[设计记录](../../../docs/design/duel-001-e2e.md)。
- 验证点：两回合中的效果发动、连锁、检索、特殊召唤、Link 与同调召唤及 Host 投降。双方按自己可见的提示、候选和区域断言执行；`hand_shuffle` 是明确允许的手牌顺序变化，卡片动作按 ID 匹配。
- 证据：`scenario.yaml` 的步骤、可见区域断言和终局目标；2026-10-09 双客户端无头回放为 `duel_finished`，Guest 获胜，报告 `out/agent-e2e-runs/1791519762-85398/scenario-report.json`。
- 边界：回放通过证明写入的协议断言成立；不证明原始文本中每个效果因果都能由客户端直接观察。真人 GUI 和 Windows 在本轮未验证。

目标审核：固定起手、写入的双端动作和可见断言、Host 投降后的 Guest 获胜**已验证**；原始剧本中无法由客户端直接观察的效果因果**部分验证**，不能仅凭回放推断；真人 GUI 体验**未验证**。

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/duel-001/scenario.yaml --timeout 80
```
