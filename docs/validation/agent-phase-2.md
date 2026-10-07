# 二期 Agent 服务验证记录

## 已执行的离线验证

- macOS CMake Debug 客户端构建成功；`ctest` 的 `agent_codec` 与 `agent_codec_sdk_contract` 通过。
- `agent_sdk` 78 项 unittest 通过。服务端 15 项测试覆盖状态持久化与重启、重传冲突、查询失败、回执、人类只读接口、Pydantic AI 结构化输出、Monty 卡库工具、客户端查询往返和启动能力探测。
- `agent_server` Ruff 与 Pyright 通过；`ygo-card-db` 的查询脚本 223 项检查通过，规则书资源由服务端工具测试读取。
- v3 无头双客户端局域网对战完成两局：双方都加载 `deck/test/test.ydk`。首次主客端分别提交 33、31 次决策；修正客户端回执队列后复跑，分别提交 152、69 次决策，双方均收到终局且胜者一致。复跑中的 221 个不同动作 ID 对应 222 次回执提交尝试，其中一次因 HTTP 客户端忙而即时重试。诊断日志保留在忽略目录 `out/agent-e2e-runs/1791366856-99434/` 与 `out/agent-e2e-runs/1791367245-6460/`。这是确定性假策略验证，不证明真实模型的决策质量。
- macOS 发布目录 `out/release-verified/ygopro-agent-macos-0.1.0/` 与同名 zip 已生成并通过静态校验；独立 `agent-server` 程序从发布根启动并通过 `/v3/ready` 的令牌与 nonce 检查，`--check-resources` 成功读取发布根技能和卡库。构建过程曾发现 PyInstaller 缺少 `genai_prices` 与 `pydantic_ai_slim` 元数据，已修复打包参数并复测。
- 配置与本地数据统一迁移到 `.agents/` 后，重新运行服务端 15 项测试、发布布局 4 项测试、CMake Debug 构建和 `ctest` 2 项，均通过。v3 无头双客户端又完成一局，双方正常结束；诊断日志在 `out/agent-e2e-runs/1791368320-25716/`。新发布目录 `out/release-agents/ygopro-agent-macos-0.1.0/` 与 zip 通过静态校验，独立 `agent-server --check-resources` 通过；zip 含 `.agents/config.toml`，无旧 `.agent/` 或本地 `.agents/data/`。

## 仍需执行

- 用户提供真实 OpenAI Responses 风格端点、模型名和密钥环境变量后，验证启动能力探测、实际模型工具调用和至少一局对战。
- Windows 构建、独立进程和双客户端验证放在最后；目前未执行。
- GUI 双客户端实际模型对战、超时与断线人工接管仍需分别实测。既有一期 GUI 剧本验证不等于二期模型链路验证。
