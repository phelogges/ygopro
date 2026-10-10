# 天子的指轮②：自动无效魔法卡效果验证

> 状态：现行验证记录；截至 2026-10-11 的 macOS 开发环境实测。场景已收入 [`tests/scenarios/angel-ring-mandatory-spell-negation/`](../../tests/scenarios/angel-ring-mandatory-spell-negation/README.md)；场景字段见[确定性场景契约](../contracts/agent-scenario-v1.md)。

人工双端录制 `8d9db8e3f281476c82a4e150c60e2b55` 启用「不洗牌」，双方完成权威终局；编译报告为 `compiled`，原始回放 `validated`。此前中止的 `f5fea40da3384c45bfc7e91952fbea28` 不参与场景。原始记录保存在 `out/duel-recordings/8d9db8e3f281476c82a4e150c60e2b55/`，不纳入 Git。

Host 先让「火山鼠」装备「团结之力」，再装备「天子的指轮」。Guest 发动「旋风」并选择「团结之力」为对象。双端观察到「旋风」的连锁 1 在处理时收到 `MSG_CHAIN_DISABLED`，而被选的「团结之力」与「天子的指轮」都留场。Host 在这个效果处理区间没有手动接受②的提示。入库 YAML 的双端有序事件断言检查效果发动、连锁处理与失效；两个区间计数断言分别要求「旋风」发动至连锁结束仅有一个 `chain_link_added`，且没有「天子的指轮」的 `effect_activated`。

验证结果：

- 加断言后的独立 HTTP v3 无头回放 `passed`：`out/agent-e2e-runs/1791652421-62934/scenario-report.json`。
- 入库后运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir --timeout 180`：六场景全部通过，零失败、零不支持；汇总报告 `out/agent-e2e-runs/batch-1791652635-66669/batch-report.json`，本场景为第 1 项。
- 本场没有同回合第二次对方魔法卡效果，不证明②“1 回合仅 1 次”的次数上限。真实模型、GUI 回放与 Windows 尚未验证。

用户已审核目标解释和双端断言，本场景现为正式回归集的一部分。
