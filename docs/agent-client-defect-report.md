# agent_client 缺陷修复报告

## 1. 范围与设计结论

本轮基于 `agent-log2.jsonl` 至 `agent-log5.jsonl`、联网客户端消息解析路径、
`ocgcore` 与对应卡片 Lua 脚本完成审计和修复。

客户端的职责是转写联网 OCG 服务器已经发送、客户端已经解析的确定事实，不是实现第二套
游戏王裁定引擎。原始 OCG 网络协议严格保持不变；单人模式和录像模式不在本轮范围。

调研确认，联网协议没有提供完整的“某个移动/召唤结果由哪一个效果造成”关联。
`ocgapi.h` 的 `query_*` 需要本地 `pduel`，无法用于连接远端 OCG 服务器的客户端。
因此客户端不再尝试生成 `cause`、印刷效果编号、`cost_for`、`material_for` 或效果对象等
推断字段。上层 agent 应结合发动候选、连锁顺序、移动原因、卡片文本和规则完成因果推理。

## 2. 已修复缺陷

### DC-001：缺少确定的决斗事件流

已增加 `card_moved`、连锁建立/开始结算/完成结算/结束/无效、召唤尝试、抽卡、LP 变化、
洗切、玩家响应、投降请求和权威终局等事件。每条事件带 `event_id`、时间戳、会话/对局 ID
及 `engine_evidence`。

`card_moved` 同时记录引擎原始 `reason_flags` 和枚举化 `reasons`，但不把同一时间附近的
连锁或召唤自动声明为其原因。

建立连接并完成握手后，所有 `duel_event` 与决策请求都会实时发送给 agent；无连接时只写
本地 JSONL。

### DC-002：公开区域卡片 ID 被抹除

双方墓地和除外区均按客户端当前可见的 `ClientCard::code` 输出。真实日志已经验证，对方
进入墓地的已公开卡可以保留 ID。若卡片从公开来源移入隐藏区时服务器发送 `code=0`，
客户端在移动前从确定公开的 `ClientCard` 缓存补充 ID，同时保留 `engine_code=0` 和
`id_provenance=public_client_cache`。表侧额外卡组会明确输出 `position=face_up`；手牌、卡组、
里侧额外卡组、其他里侧卡和叠放卡不会使用该回补路径。

### DC-003：公开展示信息没有持久化入口

新增 `cards_confirmed`，直接转写 `MSG_CONFIRM_CARDS` 的卡片 ID 与位置。Python SDK 的
`KnowledgeLedger` 支持重复卡数量、隐藏区槽位、公开区槽位和完整事件观测历史。隐藏区
洗切只清除位置对应关系；若随后有未知卡离开，该区原有确定身份会转为“可能仍在”，避免
把不确定信息继续报告为当前位置事实。agent 可根据规则和后续事实继续管理。

账本同时归约 `cards_drawn`：已知抽卡从牌组知识转入不绑定槽位的手牌确定计数；未知抽卡
不会猜测身份，并将可能受影响的牌组确定知识降级为 `possible`。

### DC-004：投降与终局缺失

本地点击投降记录 `surrender_requested`；服务端 `MSG_WIN` 单独记录 `duel_ended`。
二者不互相替代。

### DC-005：标识和版本无法稳定回放

所有 v3 请求与事件包含 `session_id`、`duel_id`、严格递增的 `event_id` 和时间戳。
同一对局的 `state_revision` 单调；`snapshot`、`json_patch` 与 `none` 的版本语义保持一致。
猜拳、先后攻选择和 `MSG_START` 复用同一 `duel_id`；`MSG_START` 不重置 revision。
每次新赛前阶段都会创建新标识，因此上一局即使异常结束也不会复用旧 ID。

### DC-006：本地响应缺少审计

`DuelClient::SendResponse` 之前记录 `decision_submitted` 及实际响应字节。agent 正式接口仍
只使用当前请求内的 `choice_id` 或选卡下标，不暴露内部编码作为策略接口。

赛前 `CTOS_HAND_RESULT` / `CTOS_TP_RESULT` 也记录语义化提交和对应 `request_id`；
`STOC_HAND_RESULT` 记录双方出拳及本地视角结果，猜拳与先后攻流程可以完整闭合。

### DC-007：区域编号含糊

区域拆分为 `main_monster` 与 `extra_monster`；同时提供零基 `slot_index` 和面向人类的一基
`slot_number`。额外怪兽区对外使用区域内索引 0/1，并用独立 `engine_sequence` 保留引擎
sequence 5/6。

### DC-008：发动候选缺少描述信息

`activatable_cards[i]` 与 `activatable_descs[i]` 的确定对应关系被序列化为
`effect_candidate`：包括描述 ID、本地描述文本、零基描述槽位偏移、候选索引和原始标志。
描述槽位偏移明确不等同于卡文的①②③，避免 `agent-log4.jsonl` 中已经证实的误标。

### DC-009：其他可直接观测信息缺失

新增以下中性事件：

- `engine_hint`：保留 `MSG_HINT` 类型、协议玩家和值；
- `cards_indicated`：转写 `MSG_BECOME_TARGET`，不武断称为“效果取对象”；
- `card_relation_added` / `card_relation_removed`：装备和持久卡片对象关系；
- `cards_confirmed`：明确展示的卡片。

### DC-010：SDK 终局状态与时间戳语义不清

SDK 新增 `state_at_last_decision()`，明确其状态来自最近一次决策请求；兼容方法
`state_for()` 保留相同语义。`observed_state_for()` 只归约明确的 LP 与终局事件，不冒充
完整场面。外层 JSONL wrapper 复用内层消息时间戳，避免同一事件出现两个时间值。

### DC-011：猜拳线值语义错误

已按客户端按钮资源与既有服务器约定修正为 `1=scissors`、`2=rock`、`3=paper`。
`decision_request`、`decision_submitted` 和 `pre_duel_hand_result` 使用同一映射；原始值仍保留
用于审计。

### DC-012：缺少回合、阶段与战斗事实

新增 `turn_started`、`phase_changed`、`attack_declared`、`battle_snapshot` 和
`attack_disabled`。状态快照现在分别保存 `engine_message`、`phase` 与 `turn_player`，不再把
当前选择消息误称为阶段。每次攻击宣言分配决斗内递增 `attack_id`，后续战斗快照或攻击无效
可通过该 ID 与宣言关联。`battle_snapshot` 明确不是完整伤害步骤结算。

### DC-013：决斗内提交缺少稳定语义

客户端用独立于 agent 待回复状态的提交上下文记住最近一次请求。实际调用
`SendResponse()` 时，若能可靠匹配，则 `decision_submitted` 包含请求 ID、决策种类、候选
动作或选中的卡片；不能可靠解码的响应只保留原始字节，不做语义猜测。该设计同时覆盖人工
capture-only 与未来 agent 控制模式。

### DC-014：移动原因被误当作权威因果

`agent-log6.jsonl` 证明 `MSG_MOVE.reason` 可能携带残留 `draw` 位。客户端继续无损输出
`reason_flags` / `reasons`，但明确标记两者非权威。SDK 只保留客户端直接可见的原始事件，
不再派生连锁结算、cost、素材或战斗因果关系；agent 可按自身策略使用这些证据。

## 3. 保留限制

- 联网协议未提供完整动作因果图，agent 必须负责卡片文本与规则推理。
- SDK 不生成任何客户端未直接观察到的因果边；agent 的推理结论不能反写成客户端事实。
- `HINT_SELECTMSG` 的数据含义依赖当前 `MSG_SELECT_*` 上下文，客户端只保留原始值。
- 对方卡片公开后进入隐藏区，服务器可能立即把后续移动 ID 刷新为 0；只有已经发生的公开
  观测和 agent 自有知识账本可以保留该知识。
- `inspect_zone` 当前只读取联网客户端的 `ClientField` 可见缓存，不调用本地引擎 query；
  仍需真实联网操作覆盖自己的卡组/额外卡组、双方墓地和除外区场景。
- `life_points_changed`、`chain_disabled` / `chain_negated` 等低频事件仍需后续真实对局覆盖。
- 新增的语义化提交、回合/阶段和 `attack_id` 战斗事件需要下一份真实联网日志完成端到端验收。

## 4. 验证策略

- 只构建 `VS2026-x64-Debug`，不得构建 `RelWithDebInfo`；
- Python 3.12 SDK 使用 `uv`、`ruff`、`pyright` 和 `unittest`；
- SDK 必须同时读取历史 v2 和当前 v3，未知事件与未知字段原样保留；
- 使用后续联网日志验证单一 `duel_id`、单调 revision、发动候选描述、公开展示、额外怪兽区、
  投降与 `MSG_WIN`；
- 任何 agent 推理字段都不能反写成客户端引擎事实。
