# 固定起手

- 类型：严格场景（schema v1）；目标见 [goal.md](goal.md)，历史目标为事后重建。
- 输入：本目录独立的 `host.ydk`、`guest.ydk`，双方使用同一构筑副本。
- 验证点：猜拳和先后攻选择后，双方可见手牌均与各自 `#main` 前五张及重复数量一致。场景止于开局 checkpoint。
- 证据：`scenario.yaml` 的 `goal.expect`；2026-10-09 双客户端无头回放 `checkpoint_passed`，报告保存在 `out/agent-e2e-runs/1791519751-85137/scenario-report.json`。
- 边界：不验证后续抽卡、卡片效果或整局胜负。用户原始目标未单独保存。

目标审核：固定双方起手及重复数量**已验证**；后续抽卡和效果**未验证**。证据是 `goal.expect` 与上述双端回放报告。

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/fixed-opening/scenario.yaml --timeout 80
```
