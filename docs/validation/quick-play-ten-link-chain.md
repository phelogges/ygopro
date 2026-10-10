# 连续速攻魔法卡连锁验证

> 状态：现行验证记录；截至 2026-10-11 的 macOS 开发环境实测。场景已收入[正式回归集](../../tests/scenarios/quick-play-ten-link-chain/README.md)；字段见[确定性场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `001aa1ecdc614b5bb3caeb792bac0989` 的清单状态为 `validated`，编译报告为 `compiled`，原始双端日志保存在 Git 忽略的 `out/duel-recordings/`。先前中止的 `54ef93fdf77c4cfc87857e01fad93c90` 不参与场景。

本场实际形成一条十项速攻魔法连锁：Host 和 Guest 交替发动「隐居者的猛毒药」各一张、「旋风」各两张、「宇宙旋风」各两张。双端原始消息和各自 HTTP v3 事件镜像显示连锁项按 1→10 加入、10→1 处理并结束。候选 YAML 对双方分别使用 41 条有序事件断言和一条区间计数断言，明确检查连锁编号、发动方和卡片 ID，以及该区间恰好十个连锁项。

验证结果：

- 原始编译草稿的双客户端 HTTP v3 无头回放通过：`out/agent-e2e-runs/1791653240-77199/scenario-report.json`。
- 增加目标断言后的候选双客户端 HTTP v3 无头回放 `passed`：`out/agent-e2e-runs/1791653440-80727/scenario-report.json`。
- 收录后运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir --timeout 180`，当前七场景全部通过，零失败、零不支持；汇总报告 `out/agent-e2e-runs/batch-1791653689-86101/batch-report.json`，本场为第 4 项。
- `agent_sdk` 场景单元测试 30 项通过；新增测试确认连锁编号逆序断言能拒绝错误顺序。

结论：用户提出的连续速攻魔法卡连锁目标已在协议和场景回放层验证，实际覆盖十项同一连锁。该验证不证明真实模型会作出相同选择，也未覆盖 GUI 演出或 Windows。用户已审核目标解释和断言范围，场景收入 `tests/scenarios/quick-play-ten-link-chain/`。
