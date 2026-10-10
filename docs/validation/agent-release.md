# Agent 服务发布验证记录

> 状态：历史验证入口；截至 2026-10-09。现行构建、发布布局和验证命令见[发布指南](../guides/agent-release.md)，现行验证范围见[验证总览](README.md)。

macOS 发布包曾通过静态布局、关键文件哈希、SQLite 结构和独立 `agent-server --check-resources` 检查，报告路径与当时环境见[二期验证记录](agent-phase-2.md)。2026-10-09 Codex 版发布包进一步从冻结服务启动 SDK 配套 CLI 并读取本地账户状态，详见[Codex 后端验证记录](agent-codex-backend.md)。这些检查没有实际登录、模型推理或 GUI 双客户端对局；Windows 构建与验证均未执行。
