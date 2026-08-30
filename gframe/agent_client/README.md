# agent_client：枚举化的 AI 协议与本地采集

`agent_client` 只观察客户端已经解析完成的 `ClientField`，将本地玩家可见的状态和
合法选择写入 JSONL；它不修改 `ocgcore`、原始网络包或 Lua 卡片脚本。

## 采集模式

配置 `system.conf`：

```ini
agent_enabled = 1
agent_host = 127.0.0.1
agent_port = 7450
agent_timeout_ms = 15000
agent_log_path = agent-log.jsonl
```

没有运行 agent 时，客户端仍会写入 `direction: "local"` 的决策记录，不等待回复
且不影响人工操作。首个状态为 `state_delta.mode: "snapshot"`；后续状态为 RFC
6902 JSON Patch，`state_delta.mode: "json_patch"`；同一状态上的新决策使用
`state_delta.mode: "none"`。

每条 JSONL 记录都包含严格递增的 `event_id` 和 `timestamp_unix_ms`。请求还包含：

- `session_id`：客户端进程一次启动的标识；
- `duel_id`：每局开始时生成的标识；
- `request_id`：仅关联一次决策请求及其 agent 回复；
- `state_revision`：请求生成时的完整可见场面版本；
- `base_state_revision`：仅 `json_patch` 存在，表示该补丁应应用的旧状态版本；
- `protocol_version`：当前写出协议为 `3`；Python SDK 同时读取 v2 与 v3。

因此，agent 必须按 `event_id` 排序；只有本地状态版本等于
`base_state_revision` 时才能应用补丁。`none` 不改变 `state_revision`。

外层 JSONL wrapper 与内层 `message` 复用同一个 `timestamp_unix_ms`，避免同一事件出现
两个相差数毫秒的时间值。

客户端收到新的 `hello_ack` 后会强制下一条决策发送 `snapshot`，而不依赖连接前的
本地 patch 基线。猜拳、先后攻选择与随后的 `MSG_START` 共用一个 `duel_id`；
下一局进入赛前阶段时生成新标识，即使上一局异常结束也不会复用旧 ID。`MSG_START` 只重置
快照基线，不回退同一对局的 `state_revision`。

## 枚举协议

所有发送给 agent 的语义值由 `agent_protocol.h` 中的 `enum class` 定义，并集中映射
为固定 ASCII 标识符。JSON 不包含面向用户的中文 `summary`、`label` 或区域/动作
显示文本。常用字段示例：

```json
{
  "decision": {
    "kind": "idle_command",
    "engine_message": 11,
    "choices": [
      {
        "id": 1,
        "action": "special_summon",
        "card": {
          "id": 13597785,
          "zone": "hand",
          "position": "hidden",
          "slot_index": 0,
          "slot_number": 1,
          "known": true
        }
      }
    ]
  }
}
```

`player` 使用 `self` / `opponent`；区域使用 `hand`、`main_monster`、
`extra_monster`、`spell_trap`、
`graveyard` 等；表示形式使用 `face_up_attack`、`face_down` 等。已知卡发送密码
`id`；对手隐藏区域和未知卡只发送数量或 `known: false`。

可发动候选额外带 `effect_candidate`。其中 `description_id` 是引擎描述 ID，
`description_offset` 是该卡描述表内的零基槽位；它不等同于卡文印刷的①②③。
`description_text` 是客户端资源中与描述 ID 对应的文本。`raw_flags`、`operation`、
`reset` 和 `forced` 均来自现有候选数据。`selection_hint.raw_value` 是上下文相关的
原始提示值，不能脱离对应的 `MSG_SELECT_*` 消息解释。

`choice.id` 仅在当前 `request_id` 内有效。agent 使用语义化的 `action` 与卡片引用
决策，再通过 `choice.id` 选择；YGOPro 内部整数响应不会作为 `decision_request` 的稳定
动作接口暴露给 agent，仅在提交后的审计事件中保留原始字节。

客户端实际提交响应时还会写出 `decision_submitted`。若提交与最近一次请求可靠匹配，事件
包含 `matched: true`、`request_id`、`decision_kind`，并尽可能包含 `choice_id`、`action`
或 `selected_indices` / `selected_cards`；无法可靠解码时只保留 `response_bytes`，不会猜测
语义。这里的原始字节仅用于审计，不是 agent 的稳定动作接口。

猜拳线值遵循现有客户端和服务器约定：`1=scissors`、`2=rock`、`3=paper`。

## 远端协议

TCP 帧格式为 4 字节大端长度 + UTF-8 JSON。客户端连接后发送 `type: "hello"`，
agent 回 `type: "hello_ack"`。后续请求类型为 `decision_request`，正式回复格式：

```json
{
  "type": "action",
  "session_id": "...",
  "duel_id": "...",
  "request_id": 17,
  "action": { "kind": "choice", "choice_id": 1 }
}
```

客户端验证 `request_id`、当前消息和 `choice_id` 后，才在本地转换为已有的
`SetResponseI` / `SetResponseB` / `SendResponse` 调用。`integer` 回复只为早期调试
兼容保留，不属于正式 agent 接口。

## 引擎观测事件

除 `decision_request` 外，客户端会以 `type: "duel_event"` 写入已由现有引擎消息确认的事件：
`card_moved`、`chain_added`、`chain_solving`、`chain_resolved`、`chain_ended`、
`chain_negated`、`chain_disabled`、`decision_submitted`、`surrender_requested` 与 `duel_ended`。
另有 `summon_attempted`、`cards_drawn` 与 `life_points_changed`，分别直接对应现有的
召唤、抽卡和 LP 服务器消息。

v3 还记录以下确定信息：

- `card_moved.reason_flags` 与解码后的 `reasons`；
- `card_moved.engine_code` 与 `card.id_provenance`：区分服务器消息直接提供的 ID、移动前
  公开客户端缓存补充的 ID，以及不可获得的 ID；
- 额外卡组卡片的位置按实际公开状态输出：表侧为 `face_up`，里侧为 `hidden`；只有前者
  才允许通过公开客户端缓存回补 ID；
- `engine_hint`：原始 `MSG_HINT` 类型、玩家字段和值；
- `cards_confirmed`：`MSG_CONFIRM_CARDS` 明确展示的卡片及位置；
- `cards_indicated`：`MSG_BECOME_TARGET` 指示的卡片，但不宣称一定是效果取对象；
- `card_relation_added` / `card_relation_removed`：装备或持久卡片对象关系。
- `pre_duel_hand_result`：双方出拳及本地视角的胜负结果；赛前实际出拳和先后攻选择另以
  带 `request_id` 的 `decision_submitted` 记录。
- `turn_started` / `phase_changed`：直接转写 `MSG_NEW_TURN` / `MSG_NEW_PHASE`，并更新
  状态快照中的 `turn_player` 和 `phase`；`engine_message` 仅表示当前引擎消息，不能当阶段。
- `attack_declared`：记录攻击方、攻击对象或直接攻击，并分配决斗内递增的 `attack_id`；
- `battle_snapshot`：记录 `MSG_BATTLE` 给出的攻守数值和战斗破坏标志；它只是战斗处理时的
  快照，不代表整个伤害步骤已经结算；
- `attack_disabled`：记录 `MSG_ATTACK_DISABLED`，并在能够确定时复用当前 `attack_id`。

事件包含 `session_id`、`duel_id`、`event_id` 和 `engine_evidence`。它只转写客户端已经
解析的 `MSG_*`／`CTOS_*` 消息；不存在的印刷效果编号、动作来源、cost 归属、素材归属、
效果对象或结算因果不会由客户端猜测。这些关系由上层 agent 结合事件顺序、候选描述、
卡片文本和规则推理。
区域使用区域内零基 `slot_index` 执行，使用一基 `slot_number` 展示。额外怪兽区额外保留
OCG 引擎使用的 `engine_sequence: 5/6`，而对外索引规范化为 `slot_index: 0/1`。

`card_moved.reason_flags` 与 `reasons` 原样来自 `MSG_MOVE`，但历史日志已证明服务端可能发送
残留原因位，因此同时标记 `reason_flags_authoritative: false` 和
`reasons_authoritative: false`。它们只能作为上层推理证据；抽卡、召唤、连锁和战斗应优先
使用各自的专用事件。

当前采集仅面向联网对局；单人模式与录像模式不写入这些事件。

远端连接完成 `hello_ack` 后，`duel_event` 与 `decision_request` 都通过同一 TCP 帧协议
实时发送；握手前已进入内存发送队列的事件记为 `direction: "queued"`，未进入队列的本地
记录才使用 `direction: "local"`。新对局边界会清理尚未处理的
旧局入站消息，同时保留已排队的权威终局事件。Agent 的 action 与 tool call 应携带
`duel_id`；客户端拒绝对其他对局执行 `inspect_zone`。

`summon_attempted` 带卡片和落点，因为 `MSG_*SUMMONING` 明确提供这些字段；
`summon_succeeded` 只带召唤类型，因为 `MSG_*SUMMONED` 本身不带卡片或批次关联。客户端
不会把多个待定召唤猜测绑定到某个成功消息。
