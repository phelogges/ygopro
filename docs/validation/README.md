# 验证总览

> 状态：现行验证入口；截至 2026-10-10 的仓库内记录。下表汇总**已有证据**；当前三场景批量回放已在本轮重跑，其余历史项目以各自记录为准。报告多在 Git 忽略的本机 `out/` 中，其他环境可能无法直接打开。

| 验证路径 | 平台与后端 | 最近有据可查的通过记录 | 未验证或不能由该记录证明 |
| --- | --- | --- | --- |
| C++ 协议编解码与 Python SDK 契约 | macOS Debug；确定性夹具 | 2026-10-09 [Codex 后端记录](agent-codex-backend.md)报告 CTest 2 项通过；[一期历史记录](phase-1-status.md)列出 v1/v2 细项 | Windows 构建和协议测试；真实模型决策 |
| 严格场景双客户端无头回放 | macOS Debug；确定性场景服务 | 2026-10-10 [场景索引](../../tests/scenarios/README.md)列出已入库场景及逐局报告；[场景制作记录](duel-scenario-authoring.md)保留 2026-10-09 当时五局的报告 | 未写入断言的规则因果；随机结果场景；Windows |
| 默认 HTTP v3 严格场景回放 | macOS Debug；双端独立离线 Agent 服务 + 共享脚本协调器 | 2026-10-10 [v3 回放记录](agent-v3-scenario-replay.md)列出删减后当前 3 个入库场景的批量报告，全部 `passed`；旧八场景报告保留为历史证据，同日默认三局双端完成 | v3 GUI、真实模型与 Windows |
| GUI 场景播放 | macOS Debug；确定性场景服务 | 2026-10-06（报告路径时间戳）[一期历史记录](phase-1-status.md)中 `duel-001` 完成双窗口终局，用户目视确认菜单和提示弹窗关闭，报告 `out/agent-e2e-runs/1791225410-98403/scenario-report.json` | 真实模型 Agent、人工 F10 接管、Windows GUI |
| 人工双客户端录制与编译 | macOS GUI + 无头回放；确定性录制 | [人工录制记录](manual-duel-capture.md)列出 `8ed56016e03248fd8e0f1807e025fab1` 回放报告；2026-10-10 [场地区场景](../../tests/scenarios/tenpai-field-set/README.md)亦有独立报告 | 新标准启动器全流程 GUI 目视验收；随机效果采样；Windows |
| v3 双客户端离线 Agent | macOS Debug；确定性假策略 | [二期记录](agent-phase-2.md)列出 `out/agent-e2e-runs/1791474298-17867/` 等完整终局及牌表绑定 | 真实模型的战术决策、完整 GUI 对局、Windows |
| Pydantic AI 真实端点 | macOS GUI；OpenAI Responses 风格端点 | 2026-10-08 [二期记录](agent-phase-2.md)确认启动能力探测与局部模型调用；故障后的回归修复另有离线测试 | 完整对局通过、模型推理摘要粒度、断线与超时人工接管 |
| Codex 后端 | macOS arm64；离线 SDK/假事件流 | 2026-10-10 [Codex 验证记录](agent-codex-backend.md)为服务端 63 项测试及静态检查通过；2026-10-09 冻结包内 CLI 无登录启动通过 | ChatGPT 登录、真实模型推理与 GUI 双客户端决斗、Windows |
| 终局取消与区域笔记 | macOS；离线服务端 + 场景回放 | [终局取消记录](agent-terminal-cancellation.md)含投降回放；2026-10-10 [隐藏区域笔记记录](agent-zone-notes.md)含魔陷区、场地区、主怪兽区证据 | 真实模型主动调用与笔记维护、Windows；场地区独立 `field` 笔记不存在 |
| 发布包静态验证 | macOS；PyInstaller + 冻结服务 | 2026-10-09 [Codex 发布记录](agent-codex-backend.md)的 `out/codex-release-check-v2/` 校验通过；更早 Pydantic AI 发布证据见[二期记录](agent-phase-2.md) | 发布包真实模型 GUI 对局、Windows 发布、签名及公证 |

执行方法见[回放指南](../guides/scenario-replay.md)、[录制指南](../guides/manual-duel-capture.md)、[真实模型对局指南](../guides/agent-live-duel.md)和[发布指南](../guides/agent-release.md)。场景数量与逐局目标以[场景索引](../../tests/scenarios/README.md)为准；本页不复制各局细节。
