# Agent 决策计时与配置验证

本轮增加逐次供应商请求、首个流事件、首段可读内容、工具、客户端查询、语义校验、持久化及整轮决策的耗时轨迹。配置模板为全部配置项补充中文注释，并增加推理强度与摘要选项。页面按对局搜索、排序，逐轮显示总耗时、最慢供应商请求和请求次数。

## 已验证

- Agent 服务端测试：35 项通过；新增测试覆盖推理强度 `none` 时摘要实际关闭，以及模型请求耗时事件。
- 发布布局测试：4 项通过；配置模板仍可用于生成发布目录。
- Ruff 检查与格式、Pyright、网页 JavaScript 语法检查通过。
- `python3.12 tools/agent-e2e.py --games 1 --deck deck/test/test.ydk --agent-v3-offline`：双方均以 `finished` 结束，均收到胜负结果；临时 SQLite 和查看令牌位于 `out/agent-e2e-runs/<run>/agent-data/`。
- 旧开发测试配置档历史移到 `out/agent-development-history/`；`.agents/data/` 根部旧 SQLite 系列文件与旧 token 已删除。真实 `config` 档及 `agent.env` 保留。

## 待验证

- 真实模型端点的新计时与摘要行为需下一次人工对局验证。离线模型不会证明供应商是否提供推理摘要，也不能代表真实请求延迟。
- macOS 发布包与 Windows 构建本轮未执行。
- 性能阈值与优化策略待真实样本收集后确定。
