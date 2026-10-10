# 双客户端场景回归集

每个场景目录保存 `scenario.yaml`、本场景固定的 `host.ydk` 与 `guest.ydk`、`goal.md` 和 `README.md`。`goal.md` 分开保留用户原话与 Agent 整理的可核查目标；历史原话缺失时标记事后重建。README 说明证据、验证状态和限制。原始双端日志、密钥及诊断报告留在 Git 忽略的 `out/`，不入库。

本回归集验证客户端在 Agent 决策前提供的合法候选、本方可见快照与事件，以及语义动作回译后能否完成预期对局。场景的机器通过结果只证明写入的断言成立；自然语言目标的充分性还需人工审核。制作步骤见[场景指南](../../docs/guides/duel-scenario-authoring.md)，流程取舍见[设计](../../docs/design/duel-scenario-authoring.md)，格式见[严格场景 v1](../../docs/contracts/agent-scenario-v1.md)与[随机场景 v2](../../docs/contracts/agent-scenario-v2.md)。新场景使用简短功能名。

场景 YAML 版本与 Agent HTTP 版本独立。当前 `tools/agent-e2e.py --scenario` 默认使用 HTTP v3；历史 HTTP v2 回归须显式指定 `--protocol v2`。本目录现收录 8 个经人工双客户端录制、Agent 审核并由用户确认的场景；原有其他剧本已从回归集移除。历史八场景回放记录只作为当时的验证证据，不能代表当前场景清单；当前证据见[验证记录](../../docs/validation/agent-v3-scenario-replay.md)、[魔术礼帽随机场景记录](../../docs/validation/magical-hats-set-shuffle.md)、[雷火沸动交界机非连锁无效记录](../../docs/validation/raikasen-nonchain-negation.md)、[天子的指轮自动无效记录](../../docs/validation/angel-ring-mandatory-spell-negation.md)、[连续速攻魔法卡连锁记录](../../docs/validation/quick-play-ten-link-chain.md)及[俱舍怒威族·独角兽③记录](../../docs/validation/kashtira-unicorn-extra-face-down-banish.md)。

批量回放当前目录下全部场景，运行 `uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario-dir`。每个场景包必须有 `scenario.yaml`、`host.ydk`、`guest.ydk`、`goal.md`、`README.md`，缺少文件会在汇总中失败；文本目标和断言的充分性仍须按[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)人工审核。批量入口对随机场景调用采样工具，逐局结果和失败日志汇总到本次运行的 `batch-report.json`。具体参数见[回放指南](../../docs/guides/scenario-replay.md)。

| 场景 | 类型 | 主要覆盖 | 本轮验证 | 尚未证明 |
| --- | --- | --- | --- | --- |
| [snake-eye-deck-set](snake-eye-deck-set/README.md) | 严格 | 黑魔女从卡组盖放「原罪宝－蛇眼」、双方展示事件与盖卡可见性 | 2026-10-09 双端终局通过 | 真实模型写魔陷区笔记、Windows 回放 |
| [tenpai-field-set](tenpai-field-set/README.md) | 严格 | 天杯龙从卡组盖放「杯满的灿幻庄」到场地区、双方展示事件与盖卡可见性 | 2026-10-10 双端终局通过 | 真实模型写场地区推断、Windows 回放 |
| [death-camel-self-set](death-camel-self-set/README.md) | 严格 | 死亡骆驼自身变为里侧守备、双方公开事件及隐藏身份边界 | 2026-10-10 双端终局通过 | 真实模型写怪兽区推断、Windows 回放 |
| [magical-hats-set-shuffle](magical-hats-set-shuffle/README.md) | 随机 | 魔术礼帽从卡组盖放两张魔陷卡、展示与三卡洗切、战斗阶段结束清理 | 2026-10-10 双端 checkpoint 两次通过；同日四场景批量回归通过 | 隐藏排列全覆盖、真实模型、GUI 与 Windows 回放 |
| [quick-play-ten-link-chain](quick-play-ten-link-chain/README.md) | 严格 | 双方交替发动速攻魔法，形成同一条十项连锁并逆序处理 | 2026-10-11 双端终局、41 条有序事件断言与区间计数断言及七场景批量回归通过 | 真实模型、GUI 与 Windows 回放 |
| [kashtira-unicorn-extra-face-down-banish](kashtira-unicorn-extra-face-down-banish/README.md) | 严格 | 俱舍怒威族·独角兽③确认对手额外卡组，选择一只怪兽里侧除外；双方展示事件与隐藏状态边界 | 2026-10-11 双端终局、目标断言及八场景批量回归通过 | 多候选选取、真实模型、GUI 与 Windows 回放 |
| [raikasen-field-nonchain-negation](raikasen-field-nonchain-negation/README.md) | 严格 | 雷火沸动交界机③在对方怪兽效果处理时取除素材、效果无效，且目标连锁只有一个连锁项 | 2026-10-11 双端终局回放、事件区间计数断言及六场景批量回归通过 | 真实模型、GUI 与 Windows 回放 |
| [angel-ring-mandatory-spell-negation](angel-ring-mandatory-spell-negation/README.md) | 严格 | 天子的指轮②自动无效旋风的魔法卡效果，不生成额外连锁项；被选装备卡留场 | 2026-10-11 双端终局、事件区间计数断言及六场景批量回归通过 | 每回合一次的次数上限、真实模型、GUI 与 Windows 回放 |

## 待覆盖的协议情况

- 已移除的基础召唤与有效连锁、长对局检索和多回合展开不再由当前入库场景专门覆盖；按[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)重新人工录制、审核并经用户确认后再补入。历史通过报告不能替代当前覆盖。
- 抛币、掷骰、随机选卡尚无入库场景，各自需要标准双端人工录制、可见事件断言及效果完成后的 checkpoint。不能用合成测试冒充真实对局覆盖。
- 结果改变后续玩家动作序列的随机效果仍需要条件分支能力；当前随机场景 v2 会明确拒绝将这类完整流程标为已验证。
- 其他复杂消息按实际录制暴露的缺口补充，分别检查 Host、Guest 的可见性，防止隐藏卡身份泄漏。

运行单个严格场景：

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/snake-eye-deck-set/scenario.yaml
```

可单独使用 `tools/sample-random-scenario.py --scenario <场景路径>` 采样随机场景；批量入口也会调用它。单次失败立即失败，覆盖目标按场景声明的次数上限统计。
