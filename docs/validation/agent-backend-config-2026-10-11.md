# Agent 后端配置选择验证

> 状态：历史验证记录，截至 2026-10-11。现行入口见[服务端 README](../../agent_server/README.md)与[Codex 指南](../guides/codex-backend.md)。

配置模板现以根级 `backend` 选择 `pydantic_ai` 或 `codex`；`[backends.pydantic_ai]` 和 `[backends.codex]` 可并存。Codex 的模型及推理强度继续由该配置档的 `codex_home/config.toml` 管理。根级共用端口、预算与存储；Pydantic AI 压缩单独配置。预算中的模型请求数和最终化保护仅供 Pydantic AI 使用。旧 `[model]` 和 `[compaction]` 会明确报错，本机未跟踪的 `.agents/config.toml` 已在保留原参数的情况下迁移。

macOS 本地验证：`agent_server` 全量测试 72 项、4 个子测试通过；覆盖两段并存时切换后端、Pydantic AI 占位模型只阻止真实启动、发布脚本接受 Codex 配置及拒绝旧格式。Ruff、Pyright、文档检查通过。`python3.12 tools/launch-agent-client.py --check` 与 `python3.12 tools/agent-release.py check-inputs --preset MacOS-Debug` 通过。默认 HTTP v3 离线回放「天声的服从」单场报告 `out/agent-e2e-runs/1791716119-82936/scenario-report.json` 为 `passed`、`duel_finished`，双端脚本各剩余 0 步，说明从新模板产生的临时配置档可启动双端服务。

未执行真实 Codex 登录、真实模型决斗、发行包构建和 Windows 验证；上述离线回放不证明这些路径。

同日补充验证：Pydantic AI 压缩配置归入其后端后，`agent_server` 的 `unittest discover` 64 项通过，Ruff、Pyright、文档检查、客户端启动前检查及发布输入检查通过。随后核对 OpenAI Docs 的 Codex 配置参考与 App Server 文档，确认 Codex 具备自动压缩，移除了服务端基于使用率调用 `thread.compact()` 的逻辑和 `[backends.codex.compaction]`；最新代码验证结果见下方。真实 Codex 压缩和模型决斗仍未执行。

移除手动压缩后的本地验证：64 项服务端单元测试、Ruff、Pyright、文档检查、客户端启动前检查均通过；真实 Codex 模型对局未执行。
