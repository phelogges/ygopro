---
name: duel-scenario-authoring
description: 将人工双客户端决斗录制与自然语言测试目标整理为可审核的协议回归场景；用于创建、复核或扩充 tests/scenarios，不用于运行时决斗决策。
---

# 决斗测试场景制作

本技能供开发 Agent 使用，不进入运行时决斗 Agent。先读[场景制作指南](../../../docs/guides/duel-scenario-authoring.md)和[制作设计](../../../docs/design/duel-scenario-authoring.md)；录制字段、场景格式和失败语义以[录制契约](../../../docs/contracts/duel-recording-v1.md)、[严格场景 v1](../../../docs/contracts/agent-scenario-v1.md)或[随机场景 v2](../../../docs/contracts/agent-scenario-v2.md)为准。

## 输入与启动

接受用户的自然语言测试目标，或已有录制 `record_id` 与目标。保留用户原话并整理可核查目标；历史目标须标明来源，不虚构录制前指令。人工完成建房、选卡组和决斗；开发 Agent 可跨轮次按 `record_id` 继续。启动、定位录制及回放命令见[录制指南](../../../docs/guides/manual-duel-capture.md)与[场景回放指南](../../../docs/guides/scenario-replay.md)。

## 审核与产物

1. 核对录制清单、双端日志、实际提交的 YDK、编译报告和时间线。若配置、完整性或提示响应配对失败，保留原始记录并报告首个缺口。
2. 根据用户目标按需查询 `ocg-rulebook`、`ygo-card-db`，逐条列出规则依据、Host/Guest 各自可观察的事实、拟采用的动作、事件及后置状态断言。不要用双端日志拼出单方未知的卡身份。
3. 严格场景使用编译器候选并执行双端回放。随机录制只产生待审草稿；先确认目标效果完成边界，再按场景 v2 契约补断言与采样验证。不要以一次偶然吻合掩盖失败。
4. 对每条自然语言目标写“已验证／部分验证／未验证”，附具体断言与报告证据。程序回放通过不自动证明目标已达成。若客户端无可观察信息、场景格式不支持后续分支或协议缺失，停止宣称成功，给出缺口和修复建议。
5. 在忽略目录准备契约要求的场景候选与审核说明，交给用户核对目标解释、断言充分性和随机覆盖。用户明确选定后才收入 `tests/scenarios/` 并更新[场景索引](../../../tests/scenarios/README.md)。原始双端 JSONL 不入 Git。

录制器和回放器负责机器判定；本技能负责解释目标、审查证据与编排工具，不在此复制协议解析或测试逻辑。不得修改游戏服务端、`ocgcore` 或卡片脚本来让剧本通过。
