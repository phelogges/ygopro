# 人工录制转回归场景指南

> 状态：现行操作指南。录制与场景字段以[录制契约](../contracts/duel-recording-v1.md)、[严格场景契约](../contracts/agent-scenario-v1.md)和[随机场景契约](../contracts/agent-scenario-v2.md)为准；历史验证见[场景制作记录](../validation/duel-scenario-authoring.md)。

1. 在录制前整理 `goal.md`：保存用户原话、可核查目标和未确定处。已有录制则标明目标是在录制后提供或事后重建。用[录制指南](manual-duel-capture.md)启动双端 GUI，明确选择严格或随机场景，并记录 `record_id`。
2. 核对清单、双端 JSONL、实际提交的 YDK、编译报告和时间线。若配置、日志完整性或提示与响应配对有误，保留原始录制并报告首个缺口。
3. 结合目标审查双方各自可见的事件和后置状态；规则或卡片事实按需查询运行资源。只对单方实际可见的信息写断言，不把双方隐藏信息拼成任一方的观测。
4. 严格场景审查编译候选后按[回放指南](scenario-replay.md)执行。随机录制的 `scenario.unverified.yaml` 只能作为草稿：确认目标随机效果结束位置，截到其后的 checkpoint，补充可见断言和结果覆盖目标，再运行采样工具。结果会改变后续动作序列的场景按契约标为暂不支持。
5. 对自然语言目标逐项写“已验证”“部分验证”或“未验证”，附断言、实际报告和限制。在 Git 忽略目录准备 `scenario.yaml`、独立的 `host.ydk`、`guest.ydk`、`goal.md` 与 `README.md`。用户审核目标解释、断言充分性和覆盖结果后，才收入 `tests/scenarios/<功能名>/` 并更新[场景索引](../../tests/scenarios/README.md)。
6. 收录后运行 `tools/agent-e2e.py --scenario-dir`，检查当前整个回归集的汇总报告。批量入口仅验证必需文件和已写的机器断言；它不能替代第 3～5 步的双视角证据审核及用户确认。

开发 Agent 的具体审核职责见[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)，设计缘由见[场景制作设计](../design/duel-scenario-authoring.md)。程序回放通过只证明写入的断言成立。
