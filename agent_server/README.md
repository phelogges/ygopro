# 本地 Agent 服务

本服务由客户端在 `YGOPRO_AGENT_ENABLE=1` 时按需启动，每个客户端独占一个进程、一个固定端口和一个本方可见视角。通信遵循 [HTTP v3](../docs/contracts/agent-http-v3.md)。游戏服务端和 CTOS/STOC 不变。

## 开发环境

使用 Python 3.12 和 uv：

```bash
cd agent_server
uv sync --group dev --locked
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check src tests
.venv/bin/pyright
```

配置模板位于项目根目录 `.agents/config.example.toml`。复制为 `.agents/config.toml`，填入 OpenAI Responses 风格端点和模型名；密钥只从 `api_key_env` 指定的环境变量读取。两客户端并行时，创建 `.agents/host.toml` 与 `.agents/guest.toml`，设置不同端口，并分别用 `YGOPRO_AGENT_CONFIG=host`、`guest` 启动。端口占用会报错，不会自动换端口。

部分兼容端点的 thinking 模式拒绝强制工具选择。此时可在该配置档的 `[model]` 下设置 `supports_forced_tool_choice = false`，让 Pydantic AI 发送自动工具选择；服务启动时仍会验证工具调用和结构化输出。默认值为 `true`。

开发时可用 `YGOPRO_AGENT_SERVER_EXECUTABLE` 指定服务可执行入口；发布后客户端默认从当前发布根目录运行 `./agent-server`。服务启动先验证 Responses 工具调用和结构化输出，失败则不会报告就绪。`--check-resources` 可单独检查发布根的两个 skill 和 `cards.cdb`；`--offline` 只供本地确定性协议测试。

在项目根目录手动启动真实模型 Agent 客户端：

```bash
python3.12 tools/launch-agent-client.py
```

该启动器使用当前 macOS Debug 客户端、`.agents/config.toml` 和本地 `.agents/data/agent.env`；完整准备步骤、普通客户端启动方式及观测入口见[手动对局说明](../docs/validation/agent-live-duel.md)。

客户端通过随机启动令牌与 nonce 验证独占子进程。人类只读页面在 `http://127.0.0.1:<port>/view`，令牌由服务首次启动生成在 `.agents/data/<profile>/viewer-token`，在页面输入后仅保存在该浏览器标签页的会话存储中。页面和 API 只显示当前配置档的单方视角；令牌不能调用决策 API。场面、事件、净差异和模型/工具轨迹持续保存在 `.agents/data/<profile>/state.sqlite3`，使用 SQLite WAL 和周期检查点；模型摘要不取代权威观察记录。页面展示供应商实际提供的推理摘要或文本；若端点未提供，会明确标注。“Agent 推断”页签单独展示对手手牌认知说明及修订历史，不将其混入权威场面。

历史查看不需要客户端或模型端点：

```bash
agent-server --view-only --config host --port 7951
```

随后打开输出的 `/view` 地址，并读取 `.agents/data/host/viewer-token` 输入页面。客方使用 `guest` 配置档、另一个端口和自己的令牌。每档只保留最近 30 天已结束对局，并以默认 2 GiB 的逻辑记录字节数为上限；进行中的对局不自动删除。手动删除已结束对局：

```bash
agent-server --delete-duel --config host --session-id <session_id> --duel-id <duel_id>
```

时间线、SSE、导出和权限边界见[可观测性契约](../docs/contracts/agent-observability-v1.md)。

## 验证和发行

无真实模型端点时，可用现有双客户端无头测试覆盖 v3 子进程、状态同步、决策和回执：

```bash
python3.12 tools/agent-e2e.py --games 1 --deck deck/test/test.ydk --agent-v3-offline
```

这个模式使用确定性测试策略，不评价模型的战术能力。macOS 发行构建与校验见 [发行说明](../docs/validation/agent-release.md)。真实端点与 Windows 路径需分别实测并记录。
