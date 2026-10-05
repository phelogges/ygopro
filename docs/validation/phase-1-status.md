# 第一期验证状态

## 已验证

- macOS `cmake --preset MacOS-Debug`、`cmake --build --preset MacOS-Debug` 成功。
- CTest 的 `agent_codec` 覆盖 20 类决斗提示、赛前选择、非法动作和截断消息；`agent_codec_sdk_contract` 将 C++ 生成的 22 个提示交给 Python SDK 解析。
- Python SDK 与 HTTP 测试端 33 项单元及本机 HTTP 测试通过；限定 `agent_sdk/` 范围的 Ruff、Pyright 通过。
- macOS Null driver 下的真实 LAN 回环验收：两个独立客户端进程、同一测试端、双方加载 `deck/test/test.ydk`，连续三局从赛前选择完成至权威 `MSG_WIN` 和 `STOC_DUEL_END`。三局两端赢家一致，没有 Agent 错误或人工操作；每端决策提交数与出站动作包数一致，双方各自三局的初始五张手牌均不同。诊断记录位于 `out/agent-e2e-runs/1791182508-84534/`。

## 待实战验证

- Windows `VS2026-x64-Debug` 预设构建与双客户端对局。
- GUI 模式下的人工 F10 接管、超时与断线后的救场需要桌面交互验收；当前无界面回归覆盖自动对局和数据过滤。

桌面自动化权限未获批准，因此 GUI 人工接管路径未用 Computer Use 测试。回归采用客户端内的非 UI 测试入口，经过真实本机服务端与 CTOS/STOC 网络，不需要窗口操作。诊断可通过 `YGOPRO_AGENT_LOG_PATH` 保留本机 JSONL 原始帧与决策记录。`MSG_WIN` 的权威胜负记入本地终局日志；第一期 HTTP 接口仅处理需要动作的决策，终局独立通知属于后续协议扩展。
