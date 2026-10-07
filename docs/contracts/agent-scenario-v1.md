# 固定牌序对局场景契约 v1

本契约定义本地双客户端回归的 YAML 场景文件。它是测试输入，不是客户端与 Agent 服务的 HTTP 协议。客户端仍只接受 `docs/contracts/agent-http-v1.md` 的语义动作，场景执行器通过 `agent_sdk` 翻译并验证动作。游戏服务端、`ocgcore` 和 CTOS/STOC 协议不变。

同一场景也可用 `tools/agent-e2e.py --scenario ... --gui` 在双窗口中播放。GUI 观看节奏和窗口生命周期见 [设计说明](../design/agent-gui-e2e.md)；场景字段及动作语义在两种模式下相同。

## 能力边界

场景使用现有房间的“卡组不洗牌”选项。双方可加载不同 YDK；各自 `#main` 的前五张卡成为初始手牌。测试器在两个客户端都完成开局摸牌后检查卡片 ID 及重复数量；前五张含额外卡组怪兽、牌组中有未知密码或无法载入的卡时预检失败。该房间选项还抑制对局内卡组洗牌；手牌洗切、掷骰、抛币及其他引擎随机取值仍可能发生，不能称为全随机事件确定性测试。测试器遇到未在场景中显式允许的已知可观测随机消息时失败，但客户端视角无法证明所有内部随机调用均未发生。

`--scenario` 启用固定牌序场景；不传该选项时保留原有随机三局回归。场景卡组可位于仓库内或项目外，文件路径相对于场景文件解析。公开示例放在 `tests/scenarios/`；私人场景无需加入 Git。

## 文件结构

```yaml
schema_version: 1
decks:
  host: ../../../deck/test/test.ydk
  guest: ../../../deck/test/test.ydk
pregame:
  host: rock
  guest: paper
  winner_chooses: go_second
steps:
  host: []
  guest: []
goal:
  kind: checkpoint
  expect:
    host:
      zones:
        - player: self
          name: hand
          count: 5
          exact:
            - {card_id: "70488851"}
            - {card_id: "24203749", count: 3}
            - {card_id: "10266279"}
```

完整的起手示例见 [`tests/scenarios/fixed-opening/scenario.yaml`](../../tests/scenarios/fixed-opening/scenario.yaml)；经过真实 LAN 双客户端验证的召唤、魔法发动及连锁示例见 [`tests/scenarios/summon-chain/scenario.yaml`](../../tests/scenarios/summon-chain/scenario.yaml)。从仓库根目录运行：

```sh
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario tests/scenarios/fixed-opening/scenario.yaml
```

`host`、`guest` 始终指两个客户端进程，不随猜拳或先后攻结果改变。`pregame.host` 与 `pregame.guest` 为 `rock`、`paper`、`scissors`，平局需按轮次给出列表。猜拳胜者收到先后攻提示，按 `winner_chooses` 选择 `go_first` 或 `go_second`。房间参数固定为单局 1v1、起手五张、LP 8000、每回合抽一张、无计时，且免除禁限卡与卡组构筑检查；场景通过不代表比赛构筑合法。

双方 `steps` 是各自的有序决策流，不比较两个客户端请求到达的先后。每步 `expect.prompt` 必填；可增加回合、阶段、LP 和可见区域等前置断言。默认情况下，出现额外提示、提示种类不符、动作无法唯一匹配或动作不合法时立即失败。可显式设置 `defaults: {optional: decline}`：对于剧本未指定的可拒绝 `chain`、`yes_no`、`effect_yes_no`，选择唯一合法的放弃候选，记录在 `ignored_decisions`；强制效果、选卡、选区和主阶段命令仍严格按步骤执行。同类提示若剧本选择器匹配候选但产生歧义，仍失败。`prompt_id` 和候选 `c0` 等 ID 只属于一次提示，不作为剧本的持久锚点。卡片密码在 YAML 中写为带引号的十进制字符串，以保留前导零。

`allowed_random_events` 默认空列表，目前只允许唯一值 `hand_shuffle`。手牌洗切不会改变按卡片 ID 匹配的脚本动作，但它仍是可观测随机事件；场景须显式声明该例外。掷骰、抛币及随机选卡不受此例外覆盖。

`chain` 是客户端对 `MSG_SELECT_CHAIN` 响应窗口的协议名称，不表示已有卡片效果组成了连锁。服务端可能询问一个没有可发动效果的响应窗口；此时客户端自动回复“放弃”，不向 Agent 服务发送决策请求，也不把该窗口记入后续 Agent 观测的事件流，场景同样不写这一步。诊断 JSONL 保留 `automatic_pass` 及原始网络帧供核查。只有存在可发动候选时，Agent 才看到 `chain` 提示。例如召唤通常怪兽「圣精灵」后有四次空响应窗口，均由客户端自动处理；真正的效果连锁发生在随后「强欲之壶」发动、「灰流丽」响应时。

## 动作与断言

`action` 使用 `docs/contracts/agent-http-v1.md` 中的语义动作种类。`choice` 与 `select_step` 使用 `match`；选卡、排序使用按期望顺序列出的 `matches`；区域使用 `places`；指示物使用 `allocations`；宣言卡片使用 `card_id`。`match` 可按动作种类、卡片 ID、控制者、当前位置与序号以及候选提供的 `description_id`、`effect_flag`、`number`、`bit`、`weight` 等字段精确匹配。默认必须匹配唯一候选；确有同形候选时，才允许写入从 1 开始的 `ordinal` 和 `expected_matches`。场景执行器解析临时候选 ID，交 `agent_sdk` 校验，客户端再校验并编码响应。场景不支持原始 CTOS 字节或跨提示的卡实体别名。

可见区域断言仅使用该客户端的本方视角：`count` 检查数量，`contains` 检查可见卡的 ID 与重复数量，`exact` 检查完整可见集合。公开场上卡可附区域序号、表示形式和客户端已知的数值；隐藏对手手牌、双方牌库内容不可断言。`zones.player` 使用 `self` 或 `opponent`，也可写视角内的 `0` 或 `1`。步骤中的 `wait_for: {timeout_ms, expect}` 等待动作后某次可见快照满足条件；下一决策前仍需成立的状态应在下一步 `expect` 再断言。客户端测试入口会在处理游戏消息后记录本方可见快照，数据仅用于本地测试，不增加 Agent HTTP 的隐藏信息。

`goal.kind: checkpoint` 在双方步骤耗尽且两端目标断言成立后报告 `checkpoint_passed`，不要求对局终局。`goal.kind: duel_end` 必须指定 `winner: host|guest|draw|any`，并核对两客户端的权威 `MSG_WIN` 与 `STOC_DUEL_END`，报告 `duel_finished`。可选的 `goal.expect.{host,guest}` 检查终局后各自可见快照。两种目标都要求步骤耗尽。`duel_end` 可指定 `surrender: {role: host|guest, expect: {host: ..., guest: ...}}`：测试器在步骤耗尽且两端后置可见断言成立后发出一次本地信号，由指定一端使用既有投降协议；赢家必须是另一端。

完整展开样例见 [`tests/scenarios/duel-001/scenario.yaml`](../../tests/scenarios/duel-001/scenario.yaml)。其 Host 卡组副本额外包含第二张 `53927851`，因为达维检索第一张后，米克拉需要从卡组特召另一张；Guest 也使用场景专用卡组副本固定剧本所需的前五张及下次抽牌。不要让共享的 `deck/test/guest1.ydk` 后续改动改变场景前置条件。人工录制转入回归集的完整对局见 [`tests/scenarios/duel-002/scenario.yaml`](../../tests/scenarios/duel-002/scenario.yaml)。

## 失败与诊断

未知字段、重复 YAML 键、无效类型/卡片密码、候选歧义、未用完的步骤、超时与未满足断言均失败。每次运行的 `scenario-report.json` 记录结果或错误、当前步骤状态、目标断言、双方起手以及最近的可见快照和决策请求；完整 JSONL 和进程日志保存在忽略的 `out/agent-e2e-runs/`。候选匹配错误在服务端状态中包含角色、步骤、选择器和当前合法候选。诊断不补入客户端未见的卡片身份。既有随机三局回归仍用于检查不同起手下的协议覆盖和对局终局。
