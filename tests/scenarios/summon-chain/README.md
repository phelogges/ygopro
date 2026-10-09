# 通常召唤与效果连锁

- 类型：严格场景（schema v1）；目标见 [goal.md](goal.md)，历史目标为事后重建。
- 输入：本目录独立的 `host.ydk`、`guest.ydk`。
- 验证点：Host 通常召唤、选怪兽区、发动魔法；Guest 在有可发动候选的连锁窗口响应；双方在 checkpoint 检查可见场面及墓地。空连锁窗口由客户端自动处理，不写成剧本步骤。
- 证据：`scenario.yaml` 的逐步 `expect`、`wait_for` 与终局前 checkpoint；2026-10-09 双客户端无头回放 `checkpoint_passed`，报告 `out/agent-e2e-runs/1791520756-7316/scenario-report.json`。
- 边界：不是完整决斗；用户原始目标未单独保存。

目标审核：召唤、发动、连锁响应及写入的终点可见状态**已验证**；完整决斗及未写入断言的规则因果**未验证**。

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/summon-chain/scenario.yaml
```
