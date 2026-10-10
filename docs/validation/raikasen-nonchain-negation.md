# 雷火沸动交界机③：非连锁无效场景验证

> 状态：现行验证记录；截至 2026-10-11 的 macOS 开发环境实测。场景已收入 [`tests/scenarios/raikasen-field-nonchain-negation/`](../../tests/scenarios/raikasen-field-nonchain-negation/README.md)；现行场景字段见[确定性场景契约](../contracts/agent-scenario-v1.md)。

人工双端录制 `e685ce92adc2425a8dfb6113791d1181` 的房间开启「不洗牌」，双方完成权威终局；编译报告为 `compiled`，原始回放 `validated`。Host 的「剑式阴极雷火沸动机」效果成为连锁 1。Guest 在处理时接受「雷火沸动交界机」③并取除一个超量素材。双端均收到 `MSG_CHAIN_DISABLED`，目标连锁从开始到结束只有一个 `MSG_CHAINING`。原始记录和编译草稿在 `out/duel-recordings/e685ce92adc2425a8dfb6113791d1181/`；一次较早中止的录制不用于场景。

为让“③不另开连锁”成为机器回归门槛，新增可选 `event_count_assertions`：以该怪兽效果的本视角 `effect_activated` 为唯一锚点，统计至首个 `chain_ended` 前的 `chain_link_added`，双端均要求恰好一次。原有有序事件断言继续检查该连锁发生 `chain_link_disabled`。计数从 Agent 服务已接受的各自事件历史读取，不混合双端隐藏信息。

验证结果：

- `agent_sdk/.venv/bin/python -m unittest discover -s agent_sdk/tests -p test_scenario.py -q`：29 项通过；构造多一个连锁项、零连锁项、缺失结束事件及重复起点的样本均被拒绝。
- `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario out/scenario-candidates/raikasen-field-nonchain-negation/scenario.yaml`：默认 HTTP v3，无头双客户端 `passed`，双方完成终局；报告 `out/agent-e2e-runs/1791651400-44971/scenario-report.json`。
- 入库后运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir --timeout 180`：五个场景全部 `passed`、零失败；汇总报告 `out/agent-e2e-runs/batch-1791651674-49898/batch-report.json`，其中本场景为 `scenario-003.json`。
- Ruff 检查、格式检查及 Pyright（0 错误）通过；Windows 与 GUI 回放尚未验证。

用户已审核场景目标和双端断言，本场景现为正式回归集的一部分。
