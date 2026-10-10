# Codex 后端验证计划与记录

> 状态：历史验证记录；截至 2026-10-10。现行验证范围见[验证总览](README.md)，初始化操作见[Codex 后端指南](../guides/codex-backend.md)。

本页区分待执行项目和实际结果。新增后端共用 [Codex 设计](../design/agent-codex-backend.md)及 [HTTP v3 契约](../contracts/agent-http-v3.md)。首次提交时仅制定验收范围；完成测试后记录命令、平台、结果和诊断路径，不把模拟测试描述为真实模型测试。

## 离线验收

| 范围 | 验收点 | 状态 |
| --- | --- | --- |
| 配置和启动 | 缺省仍选 Pydantic AI；Codex 不要求 Pydantic 端点或 API 密钥；未登录、能力缺失、冲突配置在接管前报错；不创建用户模型配置 | 配置与运行时离线检查通过；真实登录未验证 |
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

真实登录、模型推理、双客户端对局和 Windows 路径均**未验证**。Codex SDK 目前只提供 thread 归档接口，终局会归档本局 thread；归档不等于物理删除原生会话文件。

2026-10-10 将共用工具执行逻辑抽至 `agent_server/duel_tools.py`。Pydantic AI 注册函数与 Codex MCP 桥接层调用同一执行类；原 Codex 专属 `calculate` 的确定性十进制实现也移入该类，并在 Pydantic AI 注册同名工具。离线测试分别覆盖两端的批量卡片查询指标、计算和既有笔记工具。`cd agent_server && .venv/bin/python -m pytest tests -q` 为 63 项通过，Ruff、格式检查与 Pyright 通过。本次重构未运行真实模型或双客户端对局。
