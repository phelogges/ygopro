# 双客户端场景回归集

每个场景目录保存 `scenario.yaml`、本场景固定的 `host.ydk` 与 `guest.ydk`、`goal.md` 和 `README.md`。`goal.md` 分开保留用户原话与 Agent 整理的可核查目标；历史原话缺失时标记事后重建。README 说明证据、验证状态和限制。原始双端日志、密钥及诊断报告留在 Git 忽略的 `out/`，不入库。

场景的机器通过结果只证明写入的断言成立；自然语言目标的充分性还需人工审核。场景制作流程见[设计](../../docs/design/duel-scenario-authoring.md)，格式见[严格场景 v1](../../docs/contracts/agent-scenario-v1.md)与[随机场景 v2](../../docs/contracts/agent-scenario-v2.md)。新场景使用简短功能名；历史编号目录保留原名。

| 场景 | 类型 | 主要覆盖 | 本轮验证 | 尚未证明 |
| --- | --- | --- | --- | --- |
| [fixed-opening](fixed-opening/README.md) | 严格 | 双方固定起手、赛前选择 | 2026-10-09 双端 checkpoint 通过 | 后续抽卡与决斗 |
| [summon-chain](summon-chain/README.md) | 严格 | 通常召唤、魔法发动、有效连锁 | 2026-10-09 双端 checkpoint 通过 | 完整决斗 |
| [surrender-smoke](surrender-smoke/README.md) | 严格 | 投降、双端权威终局 | 2026-10-09 双端终局通过 | 真人 GUI 与模型取消时效 |
| [duel-001](duel-001/README.md) | 严格 | 两回合展开、检索、连锁、Link/同调、投降 | 2026-10-09 双端终局通过 | 未观察到的效果因果 |
| [duel-002](duel-002/README.md) | 严格 | 人工录制的长对局、公开展示事件、自然终局 | 2026-10-09 双端终局通过 | 未写入的规则因果 |

## 待覆盖的协议情况

- 尚无入库的随机场景：抛币、掷骰、随机选卡各自需要标准双端人工录制、可见事件断言及效果完成后的 checkpoint。随机场景验证工具已具备候选与采样入口，但不能用合成测试冒充真实对局覆盖。
- 结果改变后续玩家动作序列的随机效果仍需要条件分支能力；当前随机场景 v2 会明确拒绝将这类完整流程标为已验证。
- 其他复杂消息按实际录制暴露的缺口补充，分别检查 Host、Guest 的可见性，防止隐藏卡身份泄漏。

运行单个严格场景：

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/fixed-opening/scenario.yaml
```

随机场景经 Agent 与人类审核后使用 `tools/sample-random-scenario.py --scenario <场景路径>`；单次失败立即失败，覆盖目标按场景声明的次数上限统计。
