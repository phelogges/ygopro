# 验证总览

> 状态：现行验证入口；截至 2026-10-11 的仓库内记录。下表汇总**已有证据**；历史项目以各自记录为准。报告多在 Git 忽略的本机 `out/` 中，其他环境可能无法直接打开。

| 验证路径 | 平台与后端 | 最近有据可查的通过记录 | 未验证或不能由该记录证明 |
| --- | --- | --- | --- |
| C++ 协议编解码与 Python SDK 契约 | macOS Debug；确定性夹具 | 2026-10-09 [Codex 后端记录](agent-codex-backend.md)报告 CTest 2 项通过；[一期历史记录](phase-1-status.md)列出 v1/v2 细项 | Windows 构建和协议测试；真实模型决策 |
| 原生游戏消息覆盖审计与解析 | macOS Debug；静态分类 + 字节解析 + HTTP v3 回放 | 2026-10-11 [解析记录](agent-message-coverage-2026-10-11.md)：55 已解析、27 明确无需事件、4 待处理；CTest 3/3 与四场景回放 4/4 通过。前次 [18 类待处理审计](agent-message-coverage.md)保留历史证据 | 新增 14 类消息各自的真实双视角录制；已解析消息的完整语义验证；Windows |
| 严格场景双客户端无头回放 | macOS Debug；确定性场景服务 | 2026-10-11 [场景索引](../../tests/scenarios/README.md)列出八个已入库场景；[v3 回放记录](agent-v3-scenario-replay.md)报告 8/8 通过 | 未写入断言的规则因果；Windows |
| 非连锁无效的区间计数断言 | macOS Debug；人工双端录制 + HTTP v3 无头回放 | 2026-10-11 [雷火沸动交界机③记录](raikasen-nonchain-negation.md)：场景单测 29 项通过，当前六场景批量回放 6/6 `passed`，目标连锁仅一个连锁项 | 真实模型、GUI 与 Windows |
| 自动无效魔法卡效果 | macOS Debug；人工双端录制 + HTTP v3 无头回放 | 2026-10-11 [天子的指轮②记录](angel-ring-mandatory-spell-negation.md)：双端观察效果失效、无额外连锁项；入库后六场景批量回放 6/6 `passed` | 同回合第二次魔法效果、真实模型、GUI 与 Windows |
| 连续速攻魔法卡连锁 | macOS Debug；人工双端录制 + HTTP v3 无头回放 | 2026-10-11 [十项连锁记录](quick-play-ten-link-chain.md)：双端连锁加入 1→10、处理 10→1，收录后批量回放 7/7 `passed` | 真实模型、GUI 与 Windows |
| 额外卡组确认与里侧除外 | macOS Debug；人工双端录制 + HTTP v3 无头回放 | 2026-10-11 [俱舍怒威族·独角兽③记录](kashtira-unicorn-extra-face-down-banish.md)：双端展示、选卡、移动和隐藏快照断言；收录后批量回放 8/8 `passed` | 多候选选取、真实模型、GUI 与 Windows |
| 随机盖卡洗切场景回放 | macOS Debug；双客户端 HTTP v3 场景服务 | 2026-10-10 [魔术礼帽验证记录](magical-hats-set-shuffle.md)中两次独立回放及入库后批量采样通过，且原怪兽落在不同格子 | 隐藏排列全覆盖；GUI、真实模型与 Windows |
| 默认 HTTP v3 场景回放 | macOS Debug；双端独立离线 Agent 服务 + 共享脚本协调器 | 2026-10-11 [v3 回放记录](agent-v3-scenario-replay.md)列出当前 8 个入库场景的批量报告，全部 `passed`；删减前八场景报告保留为历史证据 | v3 GUI、真实模型与 Windows |
| GUI 场景播放 | macOS Debug；确定性场景服务 | 2026-10-06（报告路径时间戳）[一期历史记录](phase-1-status.md)中 `duel-001` 完成双窗口终局，用户目视确认菜单和提示弹窗关闭，报告 `out/agent-e2e-runs/1791225410-98403/scenario-report.json` | 真实模型 Agent、人工 F10 接管、Windows GUI |
| 人工双客户端录制与编译 | macOS GUI + 无头回放；确定性录制 | [人工录制记录](manual-duel-capture.md)列出 `8ed56016e03248fd8e0f1807e025fab1` 回放报告；2026-10-10 [场地区场景](../../tests/scenarios/tenpai-field-set/README.md)亦有独立报告 | 新标准启动器全流程 GUI 目视验收；随机效果采样；Windows |
| v3 双客户端离线 Agent | macOS Debug；确定性假策略 | [二期记录](agent-phase-2.md)列出 `out/agent-e2e-runs/1791474298-17867/` 等完整终局及牌表绑定 | 真实模型的战术决策、完整 GUI 对局、Windows |
| Pydantic AI 真实端点 | macOS GUI；OpenAI Responses 风格端点 | 2026-10-08 [二期记录](agent-phase-2.md)确认启动能力探测与局部模型调用；故障后的回归修复另有离线测试 | 完整对局通过、模型推理摘要粒度、断线与超时人工接管 |
| Codex 后端 | macOS arm64；离线 SDK/假事件流 | 2026-10-10 [Codex 验证记录](agent-codex-backend.md)为服务端 63 项测试及静态检查通过；2026-10-09 冻结包内 CLI 无登录启动通过 | ChatGPT 登录、真实模型推理与 GUI 双客户端决斗、Windows |
| Agent 镜像与旧版笔记工具 | macOS；Pydantic AI/Monty、Codex MCP 离线测试 | 2026-10-11 [工具收敛记录](agent-mirror-tools-2026-10-11.md)：61 项及 4 子测试通过，重复客户端查询和笔记读写不再暴露给模型，旧记录只读保留；假模型验证旧会话重建 | 真实模型能否按需回查历史；真实 Codex CLI 旧线程切换、GUI、Windows |
| 终局取消与区域笔记 | macOS；离线服务端 + 场景回放 | [终局取消记录](agent-terminal-cancellation.md)含投降回放；2026-10-10 [隐藏区域笔记记录](agent-zone-notes.md)含魔陷区、场地区、主怪兽区证据 | 真实模型主动调用与笔记维护、Windows；场地区独立 `field` 笔记不存在 |
| 发布包静态验证 | macOS；PyInstaller + 冻结服务 | 2026-10-09 [Codex 发布记录](agent-codex-backend.md)的 `out/codex-release-check-v2/` 校验通过；更早 Pydantic AI 发布证据见[二期记录](agent-phase-2.md) | 发布包真实模型 GUI 对局、Windows 发布、签名及公证 |

执行方法见[回放指南](../guides/scenario-replay.md)、[录制指南](../guides/manual-duel-capture.md)、[真实模型对局指南](../guides/agent-live-duel.md)和[发布指南](../guides/agent-release.md)。场景数量与逐局目标以[场景索引](../../tests/scenarios/README.md)为准；本页不复制各局细节。
