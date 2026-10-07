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

开发时可用 `YGOPRO_AGENT_SERVER_EXECUTABLE` 指定服务可执行入口；发布后客户端默认从当前发布根目录运行 `./agent-server`。服务启动先验证 Responses 工具调用和结构化输出，失败则不会报告就绪。`--check-resources` 可单独检查发布根的两个 skill 和 `cards.cdb`；`--offline` 只供本地确定性协议测试。

客户端通过随机启动令牌与 nonce 验证独占子进程。人类只读页面在 `http://127.0.0.1:<port>/view`，令牌由服务首次启动生成在 `.agents/data/viewer-token`。页面和 API 只显示当前服务的单方视角；令牌不能调用决策 API。场面、事件、净差异和模型/工具记录持续保存在 `.agents/data/state.sqlite3`，使用 SQLite WAL 和周期检查点；模型摘要不取代权威观察记录。

## 验证和发行

无真实模型端点时，可用现有双客户端无头测试覆盖 v3 子进程、状态同步、决策和回执：

```bash
python3.12 tools/agent-e2e.py --games 1 --deck deck/test/test.ydk --agent-v3-offline
```

这个模式使用确定性测试策略，不评价模型的战术能力。macOS 发行构建与校验见 [发行说明](../docs/validation/agent-release.md)。真实端点与 Windows 路径需分别实测并记录。
