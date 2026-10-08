# 无界面操作的局域网对局回归

测试模式让两个独立客户端进程直接调用现有 LAN API，分别扮演 host 和 guest。两端使用 Irrlicht Null driver 保留客户端状态解析、帧信号和 AgentController，直接发送原有 `CTOS_UPDATE_DECK`、`CTOS_HS_READY`、`CTOS_HS_START`，不注入鼠标或 GUI 按钮事件，也不修改服务端实现。

先以 `cmake --preset MacOS-Debug && cmake --build --preset MacOS-Debug` 构建，然后从仓库根目录运行：

```bash
python3.12 tools/agent-e2e.py --games 3 --deck deck/test/test.ydk
```

脚本启动 Python 确定性测试端及两个客户端进程，每局独立建房并保留 `out/agent-e2e-runs/` 下的结果、客户端诊断 JSONL 和进程日志。启用 `--agent-v3-offline` 时，两个临时 Agent 服务的 SQLite 与查看令牌写在本次运行的 `agent-data/e2e-host-local/` 和 `agent-data/e2e-guest-local/`，不写入 `.agents/data/`。默认单局上限 300 秒，可用 `--timeout` 调整。若某一局没有双方的 `finished` 结果，脚本返回错误。Windows 构建可通过 `--client` 指向对应 exe；Python 3.12 是测试脚本所需，游戏运行时不依赖 Python。

固定起手和脚本动作使用 YAML 场景：

```bash
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/fixed-opening/scenario.yaml
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/summon-chain/scenario.yaml
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/duel-001/scenario.yaml --timeout 80
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/duel-001/scenario.yaml --gui --timeout 80
```

场景模式单局运行，双方分别加载场景指定的 YDK；`#main` 前五张成为预期起手。它检查实际双端起手，按角色执行严格语义动作和可见状态断言，并在 `scenario-report.json` 中保存成功或失败诊断。`--host-deck`、`--guest-deck` 可覆盖场景卡组路径。写场景时遵循 [场景契约](../contracts/agent-scenario-v1.md)。房间“不洗牌”同时抑制后续卡组洗牌；其他引擎随机事件不能完全控制。原有三局随机回归继续保留。

`--gui` 使用两个正常渲染的客户端窗口观看同一剧本；`--step-delay` 指定每个明确脚本动作前的额外等待秒数，默认 1，范围 0～10。正常动画先由客户端处理，然后场景服务等待并返回下一动作；自动放弃的无关提示不增加等待。GUI 模式临时关闭快速动画，自动增加测试总超时预算，窗口在报告产生后保留到手动关闭。无 `--gui` 时仍使用无界面快速回归。详细设计见 [可视化场景验证](../design/agent-gui-e2e.md)。

服务端发来的空 `MSG_SELECT_CHAIN` 响应窗口由客户端自动回复，不进入 Agent 决策请求，也不写入场景步骤。JSONL 的 `automatic_pass` 记录与出站动作包一一核对；回归还会拒绝任何只有 `pass` 候选却被送到 Agent 的请求。

此入口只在设置 `YGOPRO_AGENT_E2E_ROLE=host|guest` 的独立测试进程中生效，不保存 `system.conf`。正式客户端仍走普通 UI 建房和 F10 接管。固定场景的客户端诊断日志上限为 100 MiB，超限写入截断标记并判测试失败；普通模式上限仍为 10 MiB。Null driver 的游戏运行路径必须经 macOS、Windows 实测，单靠编译或协议夹具不算通过。
