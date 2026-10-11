# Codex 后端验证计划与记录

> 状态：历史验证记录；截至 2026-10-11。现行验证范围见[验证总览](README.md)，初始化操作见[Codex 后端指南](../guides/codex-backend.md)。

本页区分待执行项目和实际结果。新增后端共用 [Codex 设计](../design/agent-codex-backend.md)及 [HTTP v3 契约](../contracts/agent-http-v3.md)。首次提交时仅制定验收范围；完成测试后记录命令、平台、结果和诊断路径，不把模拟测试描述为真实模型测试。

## 离线验收

| 范围 | 验收点 | 状态 |
| --- | --- | --- |
| 配置和启动 | 缺省仍选 Pydantic AI；Codex 不要求 Pydantic 端点或 API 密钥；未登录、能力缺失、冲突配置在接管前报错；不创建用户模型配置 | 配置与运行时离线检查通过；2026-10-11 独立配置档真实登录通过 |
| 目录隔离 | `CODEX_HOME`、`HOME`、工作目录与技能路径固定在当前开发或发行根；未启用通用 Shell、Web 搜索和子 Agent；服务仅暴露指定 MCP 工具 | 配置传参和无登录 SDK thread 启动通过；模型执行时待审计 |
| 决策生命周期 | 一客户端一进程、一局一 thread、一提示一 turn；thread ID 持久化；幂等重传不重复推理；重启不恢复过期 turn | 假 SDK 决策和现有会话测试通过；真实取消待验证 |
| 动作安全 | 结构化 `{reason, intent}` 经 `agent_sdk` 和客户端双重校验；无效输出达到上限后人工接管；不会生成底层协议字节 | 假 SDK 非法候选重试通过；真实模型待验证 |
| 工具与可见性 | 规则和卡库共用原技能及根卡库；状态、历史、认知说明、算术和客户端查询受本局与预算约束；隐藏身份不泄漏 | MCP 鉴权及算术往返通过；真实模型工具选择待验证 |
| 取消与故障 | 投降或胜负立即取消 turn；过期查询和迟到结果不执行；超时、登录失效、额度或模型错误按现有故障策略处理 | 既有会话取消与 MCP 过期拒绝通过；真实 Codex 中断待验证 |
| 观测 | 每轮输入、可见输出、实际返回的推理摘要、MCP 调用和阶段耗时按单局展示；缺失的推理内容如实标识 | 假事件流写入轨迹通过；真实推理输出待验证 |

以上项目可以使用假 SDK、假 Codex 事件流、假 MCP 转发和现有 HTTP v3 测试夹具验证，不依赖 ChatGPT 登录。离线测试还应检查禁用能力的配置是否实际传给 SDK，以及同一配置档不同对局的日志是否正确隔离。只有同时跑通服务端测试、Python 静态检查和现有客户端协议回归，才记录这些路径通过。

## 真实运行门槛

真实登录、工具调用、完整 GUI 决斗和发布包运行应分别记录实测报告；操作流程见[Codex 后端指南](../guides/codex-backend.md)。截至本记录，以下离线结果尚不能证明这些真实路径通过。

2026-10-09 在 macOS arm64 执行：

- `cd agent_server && .venv/bin/python -m pytest tests -q`：58 项通过，含 Codex SDK 本地启动、MCP IPC、动作校验、取消和既有服务测试。
- `cd agent_server && .venv/bin/ruff check src tests`、`.venv/bin/pyright`：通过。
- `ctest --test-dir out/build/MacOS-Debug --output-on-failure`：客户端协议相关 2 项通过。
- `.venv/bin/python -m pytest tests/test_codex_sdk_local.py -q`：SDK 配套 CLI 0.162.0 在隔离目录中无登录启动 app-server 并创建 thread，通过。
- `python3.12 tools/agent-release.py build --preset MacOS-Debug --output-dir out/codex-release-check-v2`：构建与发布校验通过，发布包位于 `out/codex-release-check-v2/ygopro-agent-macos-0.1.0/`。校验从冻结后的 `agent-server` 实际启动 SDK 配套的 Codex app-server，并调用本地账户状态接口；没有登录或请求模型。

截至 2026-10-09，真实登录、模型推理、双客户端对局和 Windows 路径均**未验证**；后续结果见下方日期记录。Codex SDK 目前只提供 thread 归档接口，终局会归档本局 thread；归档不等于物理删除原生会话文件。

2026-10-10 将共用工具执行逻辑抽至 `agent_server/duel_tools.py`。Pydantic AI 注册函数与 Codex MCP 桥接层调用同一执行类；原 Codex 专属 `calculate` 的确定性十进制实现也移入该类，并在 Pydantic AI 注册同名工具。离线测试分别覆盖两端的批量卡片查询指标、计算和既有笔记工具。`cd agent_server && .venv/bin/python -m pytest tests -q` 为 63 项通过，Ruff、格式检查与 Pyright 通过。本次重构未运行真实模型或双客户端对局。

2026-10-11 在 macOS arm64 首次用 `codex-test` 配置档完成真实 ChatGPT 登录（端口 8911），人工启动双客户端并进入赛前选择。Agent 收到第一个含三个候选的提示后约 60 秒超时交还人工；客户端日志为 `out/agent-live/agent-client-20261011T111604Z-11078.jsonl`，服务轨迹在 `.agents/data/codex-test/state.sqlite3`。Codex 线程日志显示模型 `gpt-6-luna`、低推理强度、WebSocket 请求于 11:17:52 和 11:18:07 UTC 两次因 `request timed out` 重试，决策期限内无 MCP 调用或模型答案。随后同一登录配置的最小真实模型请求返回 `OK`；分别测试显式大写代理变量和仅现有小写代理变量均成功，因此不能归因于代理变量大小写。为继续测试，仅将本地 `codex-test` 配置档的 `decision_seconds` 调到 120。

同日重新启动双客户端后，首个猜拳提示耗时 118.6 秒，客户端报 `invalid_intent`；日志为 `out/agent-live/agent-client-20261011T112754Z-26917.jsonl`。Codex 实际完成了结构化输出 `{"reason":"猜拳选择石头。","intent":{"kind":"choice","candidate_id":"c0"}}`，与合法候选一致。桥接层仅识别 `phase=finalAnswer`，实际 SDK 事件为 `phase=final_answer`，因此误判“没有最终答案”。修正后用真实事件字段形状验证；服务端全量测试 73 项及 4 个子测试通过，Ruff、Pyright 通过。该次 Codex WebSocket 请求又超时重试五次，随后回退到 HTTP 才返回；因此解析错误已修复，但网络延迟尚未解决。修复后的真实双客户端对局仍未验证。

同日下一次双客户端测试，猜拳决策在 120 秒期限耗尽，客户端日志为 `out/agent-live/agent-client-20261011T113551Z-37607.jsonl`。服务轨迹显示模型请求没有返回，收到截止时间取消；Codex 线程日志显示 WebSocket 连续超时，约 113 秒后才回退 HTTP，仍未赶上期限。根据 [Codex 官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)的自定义 provider、ChatGPT 凭据及 WebSocket 支持开关，服务端固定选用 HTTP Responses provider。使用同一隔离登录状态的 CLI 最小真实请求约 8 秒返回 `OK`；随后经本项目的 Python SDK、app-server 和 MCP 桥接配置再次真实请求，约 7 秒收到 `phase=final_answer` 与 `OK`。服务端全量测试 73 项及 4 个子测试通过，Ruff、Pyright、文档检查通过。**尚未完成修复后的真实双客户端对局**；最小请求不能代表整局性能。

同日应用修复后，用户确认真实 Codex 客户端可完成决斗。客户端日志 `out/agent-live/agent-client-20261011T114321Z-47973.jsonl` 记录连续两局：共 53 次决策请求、53 次动作提交、两次 `duel_finished`，无 `agent_error`；请求至提交耗时中位数 4.77 秒，最大 12.07 秒。该证据验证 macOS 开发环境中的真实模型、GUI 决策与终局路径，不代表战术质量、所有提示类型或 Windows 平台已验收。
