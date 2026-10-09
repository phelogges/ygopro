# 随机结果场景契约 v2

本扩展仅用于单局 1v1 的随机效果协议回归。保留 v1 的 `decks`、`pregame`、`steps`、`event_assertions` 和可见状态断言；`schema_version: 2` 必须搭配 `scenario_kind: random`。双方仍使用各自固定顺序的 YDK 和“不洗牌”房间。每个场景只聚焦一次随机操作，按 Host 和 Guest 各自可见的事件作断言，不合并隐藏信息。

随机录制从完整终局对局生成 `scenario.unverified.yaml`，其中保留所有动作供审阅。编译器不能识别效果何时完成，故候选的终局目标不能直接执行：开发 Agent 须将动作截到效果完成后，改为 `checkpoint`，编写具体可见状态断言，并审查是否有依随机结果变化的玩家动作。若存在分支动作，当前版本不能入库。

经审阅的示例结构：

```yaml
schema_version: 2
scenario_kind: random
decks: {host: host.ydk, guest: guest.ydk}
pregame: {host: rock, guest: paper, winner_chooses: go_first}
steps: {host: [], guest: []} # 实际场景填写效果完成前的固定决策
goal:
  kind: checkpoint
  expect:
    host: {turn: 1}
    guest: {turn: 1}
random_target:
  message_type: 130 # 81 随机选卡；130 抛币；131 掷骰
  max_runs: 20
  coverage: [[heads], [tails]] # 可省略；省略时只运行一次，不声称全结果覆盖
  expect: # 所有合法结果均须满足的效果完成后状态
    host: {phase: main_1}
    guest: {phase: main_1}
  cases: # 可省略；只覆写需要额外检查的结果
    - results: [heads]
      expect:
        host: {life_points: [8000, 8000]}
        guest: {life_points: [8000, 8000]}
```

`expect` 和每个 `cases[].expect` 必须分别为双方写非空断言。抛币结果为 `heads`/`tails`，骰子为 1～6；多次投掷按报文顺序写列表。程序检查两端各自只收到一次目标事件、公开结果一致；目标事件之后的同一份可见快照须同时满足 `goal.expect`、通用 `random_target.expect` 与匹配结果的 `cases[].expect`。`MSG_RANDOM_SELECTED`（81）只可检查 `cards_randomly_selected` 的结构化位置与数量，不得按隐藏卡 ID 定义覆盖目标。`event_assertions` 可分别为双方指定该事件的 `count` 和 `cards`；每张只写本端可见的 `player`、`location`、可见时的 `sequence`，匹配时要求字段集合完全相同，从而检查隐藏序号没有泄露。不能从一次通过推论所有结果已覆盖。

运行单次：`uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario PATH`。按 `coverage` 采样：`uv run --project agent_sdk --extra scenario python tools/sample-random-scenario.py --scenario PATH`。有覆盖目标时最多运行 `max_runs`（默认 20）次；任何一次协议、脚本或断言失败立即停止并报告 `failed`。到上限仍缺目标结果报告 `coverage_incomplete`，与失败分开。没有覆盖目标时只运行一次并报告 `single_passed`，不声称覆盖所有结果。报告逐次保存结果和错误。随机结果本身不受客户端固定牌序选项控制。
