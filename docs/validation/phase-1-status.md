# 第一期验证状态

## 已验证

- macOS `cmake --preset MacOS-Debug`、`cmake --build --preset MacOS-Debug` 成功。
- CTest 的 `agent_codec` 覆盖 20 类决斗提示、赛前选择、非法动作和截断消息；`agent_codec_sdk_contract` 将 C++ 生成的 22 个提示交给 Python SDK 解析。
- Python SDK、场景解释器与 HTTP 测试端共 41 项单元及本机 HTTP 测试通过；限定 `agent_sdk/` 范围的 Ruff、Pyright 通过。
- macOS Null driver 下的真实 LAN 回环验收：两个独立客户端进程、同一测试端、双方加载 `deck/test/test.ydk`，连续三局从赛前选择完成至权威 `MSG_WIN` 和 `STOC_DUEL_END`。三局两端赢家一致，没有 Agent 错误或人工操作；每端 Agent 决策提交数加客户端空窗口自动放弃数，与出站动作包数一致；双方各自三局的初始五张手牌均不同。诊断记录位于 `out/agent-e2e-runs/1791206682-5526/`。
- 固定牌序场景：双端加载同一 `deck/test/test.ydk` 时，前五张起手和场景断言一致，见 `out/agent-e2e-runs/1791206670-5307/scenario-report.json`；分别加载 `tests/scenarios/host-chain.ydk` 与 `guest-chain.ydk` 时，真实 LAN 对局完成通常召唤、魔法发动与连锁，8 次脚本决策后双方可见状态达到检查点，见 `out/agent-e2e-runs/1791206869-8765/scenario-report.json`。后一场景的双方各有 4 次空连锁窗口由客户端自动放弃，Agent 决策请求中没有仅含放弃候选的窗口。故意设置错误手牌断言的场景按预期失败并写出具体差异，见 `out/agent-e2e-runs/1791198254-3012/scenario-report.json`。
- Python SDK 与场景解释器共 41 项测试通过；限定范围的 Ruff、Pyright 通过。

## 待实战验证

- Windows `VS2026-x64-Debug` 预设构建与双客户端对局。
- GUI 模式下的人工 F10 接管、超时与断线后的救场需要桌面交互验收；当前无界面回归覆盖自动对局和数据过滤。
- 固定牌序场景只控制起手及后续卡组牌序，不控制引擎全部随机事件；尚未用完整对局脚本实测 `duel_end` 场景目标。

桌面自动化权限未获批准，因此 GUI 人工接管路径未用 Computer Use 测试。回归采用客户端内的非 UI 测试入口，经过真实本机服务端与 CTOS/STOC 网络，不需要窗口操作。诊断可通过 `YGOPRO_AGENT_LOG_PATH` 保留本机 JSONL 原始帧与决策记录。`MSG_WIN` 的权威胜负记入本地终局日志；第一期 HTTP 接口仅处理需要动作的决策，终局独立通知属于后续协议扩展。
