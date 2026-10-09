# 手动启动真实模型 Agent 客户端（macOS 开发环境）

本页描述现有 Pydantic AI 路径；Codex 后端的独立登录和验证流程见 [Codex 后端验证](agent-codex-backend.md)。

在项目根目录执行：

```bash
python3.12 tools/launch-agent-client.py
```

这个命令启动 `out/build/MacOS-Debug/gframe/ygopro`，为该客户端启用 v3 Agent，并由客户端启动 `agent_server/.venv/bin/agent-server` 子进程。启动器从 `.agents/config.toml` 读取后端配置。`pydantic_ai` 后端的 API 密钥优先从配置指定的环境变量读取，否则从本地 `.agents/data/agent.env` 读取；`codex` 后端不读取此密钥。密钥不会进入命令行参数或诊断日志。可以先用 `python3.12 tools/launch-agent-client.py --check` 检查本地文件，不启动 GUI。

使用 Codex 后端时，将配置档根级 `backend` 设为 `"codex"` 并删除整个 `[model]` 段。先执行 `uv run --project agent_server python tools/init-codex.py --profile config`，按输出的网址完成 ChatGPT 登录；需要设备码时加 `--device-code`。Codex 在 `.agents/data/<profile>/codex/codex_home/` 保存该配置档的登录状态；模型和推理强度可由用户在此目录下的 `config.toml` 自行配置。初始化工具不会预创建或覆盖该文件。不同配置档要分别初始化。

首次准备时，需要完成 macOS Debug 客户端构建和 `cd agent_server && uv sync --group dev --locked`，并在 `.agents/config.toml` 填好端点、模型、端口及密钥环境变量名。本地密钥文件只写一行，例如 `YGOPRO_AGENT_API_KEY=你的密钥`，不要纳入 Git。启动器自动把诊断日志写入 `out/agent-live/agent-client-<时间>-<PID>.jsonl`；它不修改或读取全局 Agent skill。

普通客户端另开一个终端，从项目根目录执行：

```bash
out/build/MacOS-Debug/gframe/ygopro
```

这两个窗口标题目前相同。建议先只启动 Agent 客户端，再启动普通客户端；进入联机模式时分别填写不同昵称。人工完成建房、入房和两端选卡组；Agent 从赛前选择开始接管决斗。若已有 Agent 客户端使用同一配置档端口，第二个会因端口占用而启动失败。要同时运行两个 Agent 客户端，准备两个端口不同的 `.agents/<profile>.toml`，并分别使用 `--profile <profile>` 启动。

观测页面为 `http://127.0.0.1:<配置端口>/view`；页面令牌在 `.agents/data/<profile>/viewer-token`。页面按配置档隔离，需在对局列表中选择本次对局。测试结束后正常关闭各自客户端，Agent 子进程随对应客户端退出。

若客户端提示“Agent 服务没有返回就绪消息”，先查看本次 `out/agent-live/agent-client-*.jsonl` 的 `process_start_failed`，并检查模型端点是否通过启动能力探测。部分端点在 thinking 模式下不支持强制选择工具；此时将当前配置档的 `supports_forced_tool_choice` 设为 `false`。修正配置后，可在仍打开的客户端按一次 F10 重新启动 Agent 服务；就绪后客户端会恢复接管。若仍失败，关闭该客户端后重新运行上述命令。
