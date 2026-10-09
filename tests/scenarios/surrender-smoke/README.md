# 投降与权威终局

- 类型：严格场景（schema v1）；目标见 [goal.md](goal.md)，历史目标为事后重建。
- 输入：本目录独立的 `host.ydk`、`guest.ydk`，双方使用同一构筑副本。
- 验证点：双方固定起手后由 Host 发起投降，双客户端的 `MSG_WIN` 与 `STOC_DUEL_END` 一致，Guest 获胜。
- 证据：`scenario.yaml` 的 `goal.surrender` 和 `goal.winner`；2026-10-09 双客户端无头回放 `duel_finished` 且 Guest 获胜，报告 `out/agent-e2e-runs/1791520771-7675/scenario-report.json`。
- 边界：不验证真人点击投降的 GUI 流程，也不评价 Agent 在推理中的取消时效。用户原始目标未单独保存。

目标审核：脚本发起投降与双端权威赢家一致**已验证**；真人 GUI 投降及推理中取消时效**未验证**。

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/surrender-smoke/scenario.yaml
```
