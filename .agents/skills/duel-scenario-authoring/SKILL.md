---
name: duel-scenario-authoring
description: 将人工双客户端决斗录制与自然语言测试目标整理为可审核的协议回归场景；用于创建、复核或扩充 tests/scenarios，不用于运行时决斗决策。
---

# 决斗测试场景制作

本技能供开发 Agent 使用。读取 [制作设计](../../../docs/design/duel-scenario-authoring.md)、[录制契约](../../../docs/contracts/duel-recording-v1.md)和相应的 [v1](../../../docs/contracts/agent-scenario-v1.md) 或 [v2](../../../docs/contracts/agent-scenario-v2.md) 场景契约。游戏中的 Agent 只加载规则和卡库技能，不使用本技能。

## 输入与启动

接受用户的自然语言测试目标，或已有录制 `record_id` 与目标。目标应在录制前写入 `goal.md`：分开保存用户原话和 Agent 整理的可核查目标，并指出歧义；`tools/record-duel.py --goal-file ... --scenario-kind deterministic|random --name ...` 在打开 GUI 前归档它。处理历史录制时在 `goal.md` 标明目标是录制后提供或事后重建，不虚构用户原话。人工完成建房、选卡组和决斗；Agent 可跨轮次按 `record_id` 继续。

## 审核与产物

1. 核对录制清单、双端日志、实际提交的 YDK、编译报告和时间线。若配置、完整性或提示响应配对失败，保留原始记录并报告首个缺口。
2. 根据用户目标按需查询 `ocg-rulebook`、`ygo-card-db`，逐条列出规则依据、Host/Guest 各自可观察的事实、拟采用的动作、事件及后置状态断言。不要用双端日志拼出单方未知的卡身份。
3. 严格场景使用编译器候选并运行 `tools/agent-e2e.py --scenario ...`。随机录制的 `scenario.unverified.yaml` 只是待审查草稿：确认目标随机效果完成边界，裁切到无结果依赖后续动作的 checkpoint，补 `random_target.expect`、可选结果条件与覆盖目标，再用 `tools/sample-random-scenario.py --scenario ...` 验证。随机测试的一次失败立即报告；覆盖不足单独报告，不靠重试掩盖失败。
4. 对每条自然语言目标写“已验证／部分验证／未验证”，附具体断言与报告证据。程序回放通过不自动证明目标已达成。若客户端无可观察信息、场景格式不支持后续分支或协议缺失，停止宣称成功，给出缺口和修复建议。
5. 在忽略目录准备候选包：`scenario.yaml`、本场景独立的 `host.ydk` 和 `guest.ydk`、`goal.md`、`README.md`。README 说明测试目的、关键交互、来源、验证命令、结果与限制。交给用户审核目标解释、断言充分性和随机覆盖；用户明确选定后才收入 `tests/scenarios/<功能名>/` 并更新总索引。原始双端 JSONL 不入 Git。

录制器和回放器负责机器判定；本技能负责解释目标、审查证据与编排工具，不在此复制协议解析或测试逻辑。不得修改游戏服务端、`ocgcore` 或卡片脚本来让剧本通过。
