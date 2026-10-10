# 客户端 ⇄ Agent HTTP 契约 v2

> 状态：现行一期确定性测试协议，也是 [HTTP v3](agent-http-v3.md) 的可见状态与事件基础。正式 Agent 服务只接受 v3；[v1](agent-http-v1.md) 保留为历史兼容契约。

## 范围与传输

本契约取代运行时的 [v1 决策契约](agent-http-v1.md)，不改变游戏服务端、CTOS/STOC 或 [语义动作映射](duel-actions.md)。客户端主动向 Agent 服务发送 UTF-8 JSON；服务不得反向连接客户端。`Content-Type: application/json`。默认使用本机回环地址；局域网连接沿用 Bearer token。请求和响应须限制字节数、嵌套深度、连接时间及总决策时间；超限、超时或鉴权失败均不得提交游戏动作。

`schema_version` 固定为整数 `2`。双方拒绝其他主版本，不把 v2 字段静默降级为 v1。所有标识符均为不透明字符串，所有计数、序号均为非负 JSON 整数；不得用浮点数表示序号。`database_sha256` 为实际加载卡库文件的小写 64 位十六进制 SHA-256，服务端核对本地卡库。中文只用于人可读 `description` 与 `reason`；字段名和枚举值固定使用英文。

两个客户端的 `session_id`、`duel_id`、状态、事件日志、模型上下文和查询工具权限完全隔离。即使同一服务进程同时收到双方请求，也不得合并运行时视角。录制轨迹仅可在离线验证中跨视角分析。

## 标识、版本与事件确认

| 字段 | 语义 |
| --- | --- |
| `session_id` | 客户端进程会话；新进程生成新值。 |
| `duel_id` | 单局 ID，在赛前首次决策前生成；新局生成新值。 |
| `prompt_id` | 本局内单调递增的真实决策提示 ID；`MSG_RETRY` 及人工接管后重新提交均分配新 ID。 |
| `state_version` | 本局冻结的可见快照版本，从 `1` 起严格递增；同一提示重传必须使用原版本与原内容。 |
| `event_id` | 本局内从 `1` 起连续递增的观测事件序号；空自动连锁等确认无用的通信不生成事件。 |
| `ack_event_id` | 服务端已按顺序**持久接收**的最高事件序号；尚无事件为 `0`。只确认该序号及以前的连续前缀，不代表动作已执行。 |
| `history_complete` | 客户端确认从上次已确认事件到本次提交之间，没有丢失或跳过可能影响决策的观测事实。发生队列溢出、未知关键消息或解析不完整时为 `false`。 |

客户端只在收到可校验的 `ack_event_id` 后清理不大于该值的待发送事件。HTTP 请求发出或 socket 写入成功不构成确认。服务端以 `(session_id, duel_id, event_id)` 去重；相同 ID 的重传必须内容相同，否则返回冲突。服务端不得确认未写入持久日志的事件，不得跳过缺口。事件序号跨人工控制与 Agent 控制连续；对局结束后不复用。

## 决策请求：`POST /v2/decision`

```json
{
  "schema_version": 2,
  "session_id": "client-process-id",
  "duel_id": "one-duel-id",
  "prompt_id": 42,
  "state_version": 17,
  "database_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "deadline_unix_ms": 1790000000000,
  "history_complete": true,
  "observation": {
    "self_player": 0,
    "turn_player": 0,
    "turn": 1,
    "phase": "main_1",
    "life_points": [8000, 8000],
    "disabled_field": 0,
    "graveyard_inspection_allowed": true,
    "chain_depth": 0,
    "zones": [
      {"player": 0, "name": "hand", "count": 1,
       "hidden_count": 0,
       "cards": [{"instance_id": "0:2:0", "controller": 0,
                  "location": "hand", "sequence": 0, "position": "unknown",
                  "known": true, "card_id": 12345678}]},
      {"player": 1, "name": "hand", "count": 2,
       "hidden_count": 2, "cards": []}
    ],
    "events": [
      {"event_id": 8, "kind": "phase_changed", "message_type": 41,
       "phase": "main_1"}
    ]
  },
  "prompt": {
    "kind": "idle_command",
    "description": "请选择当前操作",
    "candidates": [{"id": "c0", "kind": "normal_summon",
                    "description": "通常召唤手牌中可见的卡"}],
    "constraints": {}
  }
}
```

`observation` 是该客户端此刻可合法查看的完整快照，**不是**相对上一请求的补丁。`observation.events` 是尚未获确认的有序事件后缀，可以为空。此前经 `/v2/sync` 确认的事件不必重发。快照、事件截止点、提示和候选必须在客户端同一决策时点冻结；冻结之后收到的消息留到下一次提交。服务端先原子校验和持久接收事件与快照，再进行差异计算和动作决策。它拒绝倒退的 `state_version`；相同版本、相同提示、相同请求内容为幂等重放，内容不一致为冲突。不得将快照版本当作事件序号。

`deadline_unix_ms` 可为 `null` 或 Unix 毫秒整数。服务端不得在截止时间之后产出可执行动作。`candidate.id` 仅在本次提示有效；候选、组合约束及动作的具体形态沿用 v1 和动作契约。客户端仍须复核会话、对局、提示、版本、候选及参数，然后使用既有响应编码；`reason` 不参与编码。不得接收自由文本或原始 CTOS 字节作为动作。

### 可见状态白名单

客户端从 `ClientField` / `ClientCard` 挑选字段，不直接序列化整个 GUI 缓存。下表给出 v2 的已定义字段；可选字段只有在可见且有可信的当前值时才出现。`null` 表示合法字段但本次值未确认，不能把默认 `0` 当观测事实。静态卡库信息只由 Agent 服务按卡片 ID 查询，客户端不复制卡名或效果文本。

| 层级 | 字段 | 可见性与有效性 |
| --- | --- | --- |
| 全局 | `self_player`, `turn_player`, `turn`, `phase`, `life_points[2]`, `disabled_field`, `deck_reversed`, `graveyard_inspection_allowed`, `chain_depth` | 以本方视角映射双方；未知阶段用 `unknown`。禁用区域位掩码、牌库是否倒置、当前是否可查看墓地及连锁深度只报告客户端此刻已知的值。 |
| 区域 | `player`, `name`, `count`, `hidden_count`, `cards` | `deck`, `hand`, `monster`, `spell`, `graveyard`, `banished`, `extra`。`hidden_count = count - cards.length`；它统计未展开为单卡对象的数量，不表示卡片具有某种固定身份。双方牌组和对方手牌只给数量；不可查看墓地时该区域只给数量；对手额外和除外区域只列出身份已公开的单卡，其余计入 `hidden_count`。 |
| 卡片定位 | `instance_id`, `controller`, `location`, `sequence`, `position`, `known` | `instance_id` 是区域位置键，换区会变且可复用；不能当跨区稳定实体 ID。未知位置或表示不得凭内部缓存补全。 |
| 卡片身份 | `card_id`, `owner` | `card_id` 只在本方此刻有权查看且客户端确实知道身份时发送；`known=false` 时不得有 `card_id`。`owner` 还需当前区域内有效的对应查询。 |
| 当前公开数值 | `attack`, `defense`, `level`, `rank`, `link`, `link_marker`, `type`, `attribute`, `race`, `base_attack`, `base_defense`, `left_scale`, `right_scale`, `counters` | 正面且已知的卡，仅发送在当前区域经对应 `QUERY_*` 观察过的动态字段；未观察到就省略。攻击力或守备力为负的未知值输出 `null`。指示物只在有观察到的非空集合时给出。 |
| 当前卡片提示 | `hint_type`, `hint_value`, `description_hints` | 仅对本方当前已知身份的卡片发送。来自客户端当前 `cHint`、`chValue` 和正计数的 `desc_hints`；`description_hints` 项含原始 `description_id` 与 `count`。隐藏卡不得带这些字段；历史上隐藏期间的提示若后来变得可见，以当前快照反映。 |
| 可见关系 | `overlay_count`, `overlay_cards`, `equipped_to`, `targets` | 正面卡的素材数及已知素材身份、装备对象和指定对象。素材对象使用宿主位置键派生的局部键；关系目标均为位置键，目标离位后不可当成持久实体引用。 |

本轮尚未纳入玩家提示的当前状态、链上详细对象、攻击者与攻击目标、额外区细分等字段；这些须逐项确认来源、可见性、有效期和测试后扩充。不能因为字段存在于 `ClientField` / `ClientCard` 就直接输出。`reason`、`status`、UI 选择标记及内部命令标记不属于快照事实。

`position` 可取 `face_up_attack`、`face_up_defense`、`face_down_attack`、`face_down_defense`、`face_up`、`face_down` 或 `unknown`。`face_up`／`face_down` 只表示通用正反面位掩码，不推断攻守表示。场上里侧卡不得附带动态数值；墓地等公开区域的通用正面表示可附当前确实观察到的查询字段。

可见性过滤必须同时作用于快照、事件、提示候选、服务端镜像、只读工具及日志中的模型输入。暂时不可查看某区域时，当前快照只给允许的数量等信息；此前真正观察过的事件可以留在历史，供 Agent 像人一样凭记忆判断。受限候选使用不透明 `candidate.id` 精确选择，不因执行需要而泄露隐藏 `card_id`。候选不能以描述文本旁路泄露身份。

### 观测事件

每个事件含 `event_id` 和 `kind`。来自游戏消息的事件还含 `message_type`；本地人工／Agent 控制切换事件使用 `source: "client_control"`。事件只附协议或客户端 GUI 确实观察到的字段。首版已解析回合／阶段、抽卡、移动、终局、提示、展示、连锁发动与结算、LP 变化、攻击／战斗、表示形式、盖放、指定对象、召唤、洗牌、硬币与骰子结果，以及卡片与玩家提示等消息。`MSG_CARD_HINT` 在关联卡片当前可见且身份已知时记录 `card_hint_observed`，包含本方视角的 `player`、去除叠放标记的 `location`、`sequence`、`hint_type`、`value`；关联卡片不可见时不生成事件，避免泄露隐藏信息。`MSG_PLAYER_HINT` 记录 `player_hint_observed`，包含 `player`、`hint_type`、`value`。提示值保留观察到的原始值；仅 `HINT_OPSELECTED` 的公开选项值 `60`／`61` 额外给出 `option: "heads"`／`"tails"`，对应 GUI 展示的正面／反面，不据此判断卡片效果是否成功。洗牌消息只记录 `shuffle_message_observed`，不凭消息推断未知牌序。移动消息给出收到的原始 `reason_flags`，但不能补写未观测到的战斗破坏、素材用途、效果已使用等因果。已确认对历史不产生必要事实的更新包和决策提示不入事件日志。其余消息或已知消息的截断内容记录 `unparsed_game_message` 并把 `history_complete` 置为 `false`；服务端拒绝自动决策。绝不把未知消息的原始包、隐藏卡 ID 或服务端私有字段传给 Agent。

`MSG_TOSS_COIN`（130）生成 `coin_tossed`，`MSG_TOSS_DICE`（131）生成 `dice_rolled`；二者均含本方视角的 `player`、`count` 和按报文顺序排列的 `results`。硬币结果使用 `"heads"`／`"tails"`，与 GUI 展示一致（原始值 `1`／`0`）；骰子结果为 `1` 至 `6` 的整数。`count` 必须等于结果数；单包硬币最多 20 次、骰子最多 5 次。长度、次数、投掷者或结果非法时按解析不完整处理。结果事件只报告公开随机结果，不推断猜测是否命中或效果结算因果。例如：

```json
{"event_id": 9, "kind": "coin_tossed", "message_type": 130,
 "player": 1, "count": 1, "results": ["tails"]}
```

`MSG_RANDOM_SELECTED`（81）生成 `cards_randomly_selected`，包含本方视角的执行玩家 `player`、`count` 和按收到的报文顺序排列的 `cards`。每项仅含选中卡所在的本方视角 `player` 与原始 `location`；当前位置确实可查看时才含 `sequence`。双方牌组、对方手牌、对方额外卡组与除外区，以及本次不可查看的墓地不提供序号。报文本身没有卡片 ID，事件也绝不从客户端缓存补充 ID 或推断选中的是哪张卡。报文的玩家、数量（`uint8`，1–255）、区域、长度非法时置为解析不完整。例如，对方手牌和己方怪兽区各选中一张：

```json
{"event_id": 10, "kind": "cards_randomly_selected", "message_type": 81,
 "player": 1, "count": 2,
 "cards": [{"player": 1, "location": 2},
           {"player": 0, "location": 4, "sequence": 2}]}
```

`MSG_SHUFFLE_SET_CARD`（36）生成 `set_cards_shuffled`，只含本方视角的 `player`、`zone`（`monster` 或 `spell`）及 `count`（2–5）。事件不含卡片 ID、洗切前后格子序号或对应关系；洗切后的身份以随后各自可见的快照为准。消息长度、区域、数量或参与卡片位置非法时置为解析不完整。例如：

```json
{"event_id": 11, "kind": "set_cards_shuffled", "message_type": 36,
 "player": 1, "zone": "monster", "count": 3}
```

牌库、场地关系和猜拳消息按以下表格转换；所有 `player` 均为本方视角（自己为 0），报文长度或字段非法时按解析不完整处理。事件中的 `cards` 按报文顺序排列。位置项只含 `player`、`location`，在该位置可查看时才含 `sequence`；关系与交换事件不附原始卡片 ID。

| 游戏消息 | 事件 `kind` | 可观测字段 |
| --- | --- | --- |
| `MSG_CONFIRM_DECKTOP`（30）、`MSG_CONFIRM_EXTRATOP`（42） | `deck_cards_revealed` | `player`、`zone`（`deck`／`extra`）、`count`、`cards`。每项含本次公开展示的 `card_id`（若报文非零），按牌顶至牌底的展示顺序排列，不含隐藏区域序号；以后常规牌库快照仍不保留身份。 |
| `MSG_SWAP_GRAVE_DECK`（35） | `grave_deck_swapped` | `player`；只报告区域交换，不据此推断单卡身份、牌序或额外卡组移动细节。 |
| `MSG_REVERSE_DECK`（37） | `deck_reversal_changed` | `deck_reversed`；当前倒置状态也写入快照，供中途接管。 |
| `MSG_DECK_TOP`（38） | `deck_top_observed` | `player`、`top_offset`、`card_reversed`；报文公开了卡片 ID 时带 `card_id`。`top_offset` 相对牌顶，不作为内部绝对序号；高位标记只表示原生客户端的单卡倒置状态。 |
| `MSG_SWAP`（55） | `cards_swapped` | 两个场上原位置组成的 `cards`；即使报文携带卡片 ID，事件也不输出，以免泄露里侧卡身份。 |
| `MSG_FIELD_DISABLED`（56） | `field_disabled_changed` | `value` 是已转换成本方坐标的禁用区域位掩码，与快照 `disabled_field` 一致。 |
| `MSG_EQUIP`（93）、`MSG_CARD_TARGET`（96）、`MSG_CANCEL_TARGET`（97） | `equip_relation_established`、`card_target_relation_added`、`card_target_relation_removed` | 两个位置组成的 `cards`，依次为关系来源和对象；持续关系与一次性的 `MSG_BECOME_TARGET` 有别。 |
| `MSG_ADD_COUNTER`（101）、`MSG_REMOVE_COUNTER`（102） | `counter_added`、`counter_removed` | `counter_type`、`count` 和含单个位置的 `cards`；卡片身份不从 GUI 缓存补出。 |
| `MSG_MISSED_EFFECT`（120） | `effect_timing_missed` | 含关联位置的 `cards`，不可查看的位置省略序号。原生 GUI 会把该消息的卡名写进可见日志，因此报文非零的 `card_id` 也是本次公开展示信息。 |
| `MSG_HAND_RES`（133） | `hands_compared` | `self_choice`、`opponent_choice`，取值 `rock`、`paper`、`scissors`。它也可能由对局中的卡片效果触发。 |

例如，对方额外牌组展示一张卡的事件仅记录这次展示；对方手牌或里侧场上卡的关系事件不得附隐藏序号或身份。静态消息分类见[客户端游戏消息覆盖审计](../design/agent-message-coverage.md)。

`MSG_CONFIRM_CARDS`（31）的 `cards_revealed` 事件保留报文公开展示的卡片 ID；对于可定位的场上魔陷区，还保留本方视角的 `player`、`location` 与 `sequence`。录制 `6aba04db61ae42fc8301a5165b60bb75` 中，对手盖放 `89023486` 时，`card_set` 与后续 `cards_revealed` 都指向魔陷区序号 3。当前快照仍把该盖卡标为 `known=false`，历史展示事实由 Agent 通过事件和独立笔记维护，不写回权威卡片身份。

`MSG_CHAINING`（70）的 `effect_activated` 对场上怪兽（`location=4`）附上报文本身的本方可见 `sequence`；其他区域仍按可见性边界处理，不从隐藏手牌或牌库报告序号。`MSG_POS_CHANGE`（53）的 `position_changed` 保留本方视角的 `player`、`location`、`sequence` 与前后表示形式，事件自身不补卡片 ID。录制 `62e7b8fbe66b4bccab6db404a9b3c117` 中，观察方先见到死亡骆驼表侧身份，再收到同为主怪兽区序号 0 的 `effect_activated(card_id=2326738)` 和 `position_changed(face_up_attack -> face_down_defense)`；当前里侧快照仍为 `known=false`。历史身份只可写入独立的 Agent 推断笔记，不写回权威快照。

快照比较生成的是**净状态差异**，与上述有序观测事件分开。相同卡片 ID 的多份副本、手牌重排及隐藏区进出不能凭快照推断为同一实体移动；只有已观测事件明确关联时才表达移动关系。

## 决策响应

```json
{
  "schema_version": 2,
  "session_id": "client-process-id",
  "duel_id": "one-duel-id",
  "prompt_id": 42,
  "state_version": 17,
  "ack_event_id": 8,
  "reason": "选择通常召唤。",
  "action": {"kind": "choice", "candidate_id": "c0"}
}
```

响应中的四个标识和 `state_version` 必须精确对应当前待决策请求。`ack_event_id` 必须覆盖此次请求末尾事件，并不得超过服务端实际持久接收的连续前缀。客户端可以清理获确认事件，但只有在动作再次通过本地校验且提示仍有效时才执行动作。重复、迟到、冲突或未知候选的响应均不得执行。

## 事件分批同步：`POST /v2/sync`

当未确认事件过多，决策请求可能超出大小限制时，客户端可先按序分批同步事件；对局结束的终局事件也可经此接口通知服务端。第一次 `/v2/sync` 可以早于本局第一次决策请求。普通决策若大小允许，直接通过 `/v2/decision` 同步事件和快照，省去额外往返。`/v2/sync` 只同步事件，不修改权威快照，也不返回动作。

```json
{
  "schema_version": 2,
  "session_id": "client-process-id",
  "duel_id": "one-duel-id",
  "database_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "events": [{"event_id": 7, "kind": "cards_drawn", "message_type": 90,
              "player": 0, "count": 1}],
  "history_complete": true
}
```

```json
{"schema_version": 2, "session_id": "client-process-id",
 "duel_id": "one-duel-id", "ack_event_id": 7}
```

服务端按连续前缀确认；同一批原样重传幂等。决策请求仍须携带当时的完整快照和未确认的剩余事件。单个事件无法放入受限请求体，或者完整快照本身超限时，不得截断、抽样或悄悄丢弃；交还人工并记录诊断。对历史事件设置数量和大小上限时，达到上限前先同步，不能先丢弃再把 `history_complete` 设为 `true`。

## 恢复状态：`POST /v2/status`

客户端从人工模式通过 F10 恢复 Agent 接管前，查询服务端已接收的状态版本与事件前缀。请求不含快照、事件或动作：

```json
{"schema_version": 2, "session_id": "client-process-id",
 "duel_id": "one-duel-id",
 "database_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

```json
{"schema_version": 2, "session_id": "client-process-id",
 "duel_id": "one-duel-id", "state_version": 17, "ack_event_id": 8}
```

从未保存本局快照时 `state_version=0`；从未接收事件时 `ack_event_id=0`。客户端核对版本及确认序号不得小于本地已确认值，也不得超过本地已分配值。符合条件后，清理已确认事件，再冻结当前待决策提示的新快照并继续。结果冲突或不可验证时交还人工；状态查询本身不推进游戏。

## 错误、恢复和人工接管

非 2xx 响应使用 JSON 错误体：

```json
{"schema_version": 2,
 "error": {"code": "history_incomplete", "message": "观测事件不连续"}}
```

错误码至少包含 `unsupported_version`、`invalid_request`、`database_mismatch`、`event_gap`、`event_conflict`、`stale_state`、`state_conflict`、`history_incomplete`、`unsupported_prompt`、`invalid_intent`、`payload_too_large`、`internal_error`。客户端本地仍有 `stale_prompt`、`invalid_action`、`timeout`、`transport_error` 等。非 2xx 不含动作；客户端不得借错误响应推进游戏。

`history_complete=false`、事件缺口、重要消息未解析、无法恢复的状态版本冲突、动态字段泄露、快照过大、超时或断线时，当前提示交还人工。完整快照可恢复当前可见场面，但不能补回已经丢失的事件经过。人工操作期间继续采集可见事件和状态；恢复 Agent 前同步这些事实与控制权切换标记。若期间历史已不完整，不让模型在假定完整历史的情况下继续。

超时或断线后，服务端可能已经持久接收请求；客户端不能仅因收不到响应就假定未处理，也不能执行旧动作。恢复时按同一会话与对局核对确认序号和状态版本，重传原内容以利用幂等性；随后只针对仍然有效的新提示决策。服务端即使返回旧提示动作，客户端也必须丢弃。`MSG_RETRY` 总是生成新 `prompt_id`。

客户端一次最多有一个未完成 HTTP 请求。状态接收的原子性、幂等结果保存、事件确认与快照检查点见 [状态处理设计](../design/agent-state-v2.md)。

## 明确延后

- Agent 主动要求客户端查询场面：首版工具只查服务端已确认的镜像；确有快照无法承载的合法可见信息时再设计客户端主动续接协议。
- LLM harness、开源 Agent 框架、技能调用和模型供应商接口：二期设计。
- 三局两胜、换备牌、双打、观战、单机残局及其他语言。
- 客户端与服务端之间的公网 TLS／部署方案。
