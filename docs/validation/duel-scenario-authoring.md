# 场景制作与随机协议验证记录

> 状态：历史验证记录；截至 2026-10-09。现行操作见[场景制作指南](../guides/duel-scenario-authoring.md)，现行验证范围见[验证总览](README.md)。

2026-10-09，macOS Debug：

- `cmake --build --preset MacOS-Debug`、`ctest --test-dir out/build/MacOS-Debug --output-on-failure` 均通过（CTest 2 项）。`MSG_RANDOM_SELECTED` 解析、隐藏序号过滤及最多 255 张的边界由 C++ 编解码测试覆盖；GUI 中一次选出超过 10 张卡的实际行为尚未目视验证。
- `agent_sdk` 全量 90 项单元测试、根目录 Python 11 项测试、Ruff、项目级 Pyright、`git diff --check` 均通过。测试涵盖随机场景 v2 的结果匹配和未命中目标结果、随机选卡双视角字段断言、随机编译候选、录制前归档 `goal.md`，以及 checkpoint 必须在目标事件后由同一快照满足全部断言。
- Agent 服务端 49 项测试及项目级 Pyright 通过。HTTP 测试需要绑定本机临时端口，在允许该操作的环境中执行；沙盒内的首次运行因端口绑定被禁止而失败，非代码断言失败。
- 新开发技能 `duel-scenario-authoring` 通过 skill-creator 的 `quick_validate.py`。当时入库的五个场景均可由 `Scenario.load` 读取，且各自具备 `scenario.yaml`、双方 YDK、`goal.md` 和 README；当前场景清单见[场景索引](../../tests/scenarios/README.md)。
- 五个严格场景分别经真实双客户端无头回放通过：`fixed-opening` → `checkpoint_passed` (`1791519751-85137`)；`summon-chain` → `checkpoint_passed` (`1791520756-7316`)；`surrender-smoke` → `duel_finished`、Guest 获胜 (`1791520771-7675`)；`duel-001` → `duel_finished`、Guest 获胜 (`1791519762-85398`)；`duel-002` → `duel_finished`、Host 获胜 (`1791520794-8176`)。详细报告均在忽略的 `out/agent-e2e-runs/<ID>/scenario-report.json`。

随机效果没有符合新标准的人工双端录制；因此随机场景 v2 的实际双客户端回放、结果覆盖采样及人类审核入库仍待验证。当前仅能确认解析器、编译器、采样逻辑和协议事件的局部测试。真实模型决斗及 Windows 也不属于本次验证结果。
