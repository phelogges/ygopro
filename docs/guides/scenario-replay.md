# 双客户端场景回归操作指南

> 状态：现行操作指南；macOS 已运行，Windows 待验证。格式与失败语义见[严格场景契约](../contracts/agent-scenario-v1.md)和[随机场景契约](../contracts/agent-scenario-v2.md)；执行证据见[验证总览](../validation/README.md)。

测试模式让两个独立客户端进程直接调用现有 LAN API，分别扮演 host 和 guest。两端使用 Irrlicht Null driver 保留客户端状态解析、帧信号和 AgentController，直接发送原有 `CTOS_UPDATE_DECK`、`CTOS_HS_READY`、`CTOS_HS_START`，不注入鼠标或 GUI 按钮事件，也不修改服务端实现。

先以 `cmake --preset MacOS-Debug && cmake --build --preset MacOS-Debug` 构建，然后从仓库根目录运行：

```bash
python3.12 tools/agent-e2e.py --games 3 --deck deck/test/test.ydk
```

默认路径使用 Agent HTTP v3：脚本为 Host 和 Guest 分别准备临时配置，两个客户端各自启动离线 Agent 子服务，每局独立建房。服务数据及查看令牌放在本次运行的 `out/agent-e2e-runs/<run>/agent-data/e2e-host-local/` 和 `e2e-guest-local/`，不会写入 `.agents/data/`；结果、客户端诊断 JSONL 和进程日志也保存在本次运行目录。`--agent-v3-offline` 只是默认 `--protocol v3` 的旧别名。仅排查旧路径时显式使用 `--protocol v2`；这会改用历史 HTTP v2 确定性测试服务。默认单局上限 300 秒，可用 `--timeout` 调整。若某一局没有双方的 `finished` 结果，脚本返回错误。Windows 构建可通过 `--client` 指向对应 exe；Python 3.12 是测试脚本所需，游戏运行时不依赖 Python。

固定起手和脚本动作使用 YAML 场景：

```bash
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/snake-eye-deck-set/scenario.yaml
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/tenpai-field-set/scenario.yaml --gui --timeout 120
```

场景模式单局运行，双方分别加载场景指定的 YDK；`#main` 前五张成为预期起手。默认 v3 路径由共享脚本协调器为两个独立 Agent 服务提供动作，同时走首次牌表、客户端查询、动作回执、终局同步与本视角事件持久化链路。它检查实际双端起手，按角色执行严格语义动作和可见状态断言，并在 `scenario-report.json` 中记录 `agent_http_protocol`、成功或失败诊断。`--host-deck`、`--guest-deck` 可覆盖场景卡组路径。写场景时遵循[场景契约](../contracts/agent-scenario-v1.md)；YAML `schema_version` 与 HTTP 版本独立。房间“不洗牌”同时抑制后续卡组洗牌；其他引擎随机事件不能完全控制。三局随机回归继续保留。

批量回放当前入库的全部场景：

```bash
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario-dir
```

`--scenario-dir` 不带路径时扫描 `tests/scenarios/`，也可指定其他目录；递归查找 `scenario.yaml`，按相对路径排序，逐局启动独立无头回放。随机场景调用采样入口，按场景的覆盖目标与次数上限执行；没有公开覆盖目标时只运行一次，并将 `single_passed` 汇总为该场景通过，不宣称所有隐藏结果已覆盖。每个场景包须包含两副独立 YDK、`goal.md` 和 `README.md`；文件缺失记为失败。单局失败后仍继续其他场景，最终在 `out/agent-e2e-runs/batch-<时间戳>-<进程号>/batch-report.json` 汇总状态、逐局报告、日志和诊断目录；任一场景失败或覆盖不足则命令返回非零。可传 `--protocol v2`、`--client`、`--cards-db`、`--timeout`；批量模式不接受 `--gui`、`--games`、卡组覆盖或录制选项。场景能否证明自然语言测试目标，仍须按[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)审查，批量通过只证明机器断言成立。

经人工审阅的随机效果场景使用 [v2 场景契约](../contracts/agent-scenario-v2.md)，可单独运行 `python3.12 tools/sample-random-scenario.py --scenario <路径>`。它每次启动一局独立双客户端回放并保存结果；一次协议或断言失败立即停止，达到采样次数仍缺目标结果时报告覆盖不足。入库场景的当前清单见[场景索引](../../tests/scenarios/README.md)。

`--gui` 使用两个正常渲染的客户端窗口观看同一剧本；`--step-delay` 指定每个明确脚本动作前的额外等待秒数，默认 1，范围 0～10。正常动画先由客户端处理，然后场景服务等待并返回下一动作；自动放弃的无关提示不增加等待。GUI 模式临时关闭快速动画，自动增加测试总超时预算，窗口在报告产生后保留到手动关闭。无 `--gui` 时仍使用无界面快速回归。详细设计见 [可视化场景验证](../design/agent-gui-e2e.md)。

服务端发来的空 `MSG_SELECT_CHAIN` 响应窗口由客户端自动回复，不进入 Agent 决策请求，也不写入场景步骤。JSONL 的 `automatic_pass` 记录与出站动作包一一核对；回归还会拒绝任何只有 `pass` 候选却被送到 Agent 的请求。

此入口只在设置 `YGOPRO_AGENT_E2E_ROLE=host|guest` 的独立测试进程中生效，不保存 `system.conf`。正式客户端仍走普通 UI 建房和 F10 接管。固定场景的客户端诊断日志上限为 100 MiB，超限写入截断标记并判测试失败；普通模式上限仍为 10 MiB。Null driver 的游戏运行路径必须经 macOS、Windows 实测，单靠编译或协议夹具不算通过。
