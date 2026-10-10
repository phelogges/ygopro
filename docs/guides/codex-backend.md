# Codex 后端初始化与真实对局指南

> 状态：现行操作指南；Codex 真实登录与模型决斗尚未在[验证记录](../validation/agent-codex-backend.md)中标为通过。后端职责见[设计](../design/agent-codex-backend.md)。

使用 Codex 后端时，将配置档根级 `backend` 设为 `"codex"` 并删除整个 `[model]` 段。先执行 `uv run --project agent_server python tools/init-codex.py --profile config`，按输出的网址完成 ChatGPT 登录；需要设备码时加 `--device-code`。Codex 在 `.agents/data/<profile>/codex/codex_home/` 保存该配置档的登录状态；模型和推理强度可由用户在此目录下的 `config.toml` 自行配置。初始化工具不会预创建或覆盖该文件。不同配置档要分别初始化。

使用登录后的配置档运行 `python3.12 tools/launch-agent-client.py --profile <profile>`，人工客户端启动、建房、牌组与观测操作见[真实对局指南](agent-live-duel.md)。测试时覆盖赛前选择、工具调用、动作回执及对手投降后的取消，并核对同一局的网页与 SQLite 记录。发布包另按[发布指南](agent-release.md)运行离线与 GUI 验证。
