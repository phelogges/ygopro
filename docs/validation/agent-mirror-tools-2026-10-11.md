# Agent 镜像查询与笔记工具收敛验证

> 状态：历史验证记录；截至 2026-10-11，适用于 macOS 本地 Python 服务测试。现行工具语义见[工具契约](../contracts/agent-tools-v1.md)。

## 变更与验证

Pydantic AI、CodeMode 和 Codex MCP 不再向模型提供 `client_inspect_zone`、`client_inspect_card`、`read_zone_note`、`write_zone_note`。`current_state`、`zone_state`、`card_state`、`event_history` 仍按决策版本读取已确认镜像；决策输入不再自动附带旧版笔记。旧版模型会话在继续对局时重建，先提供已确认完整快照，不把原会话中的笔记文本带入新决策。HTTP v3 客户端查询路径保留作兼容和诊断；旧版笔记 SQLite 记录及人类网页的只读展示保留。

- macOS：`agent_server/.venv/bin/pytest agent_server/tests -q --tb=short`，61 项及 4 个子测试通过；包含 Monty 镜像区域查询不发起客户端往返、模型在后续决策主动回查旧展示事件、两种后端不注入旧版笔记、Codex MCP 工具列表、旧版笔记记录只读页面、保留的 HTTP 查询状态机。
- macOS：在 `agent_server/` 运行 `.venv/bin/pyright`，0 错误；所改 Python 文件通过 Ruff。
- 文档检查 `python3 tools/check-docs.py` 通过；`git diff --check` 通过。

本次未执行真实模型或 GUI 对局，也未执行 Windows 验证。跨版本会话重建由离线假模型覆盖，真实 Codex CLI 的旧线程切换仍需在用户提供可用登录环境后实测。
