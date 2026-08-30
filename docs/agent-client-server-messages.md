# 客户端解析服务端消息

网络层 `DuelClient::ClientRead` 从 libevent 缓冲区取出完整包，并交给
`HandleSTOCPacketLan`。其中 `STOC_GAME_MSG` 会继续传入
`DuelClient::ClientAnalyze`，由该函数解析游戏引擎消息。

`ClientAnalyze` 的主要职责如下：

- `MSG_UPDATE_DATA`、`MSG_UPDATE_CARD` 更新 `ClientField` 内的区域和卡片；
- 移动、召唤、抽卡、连锁等事件改变场面、手牌/卡组数量、墓地和连锁状态；
- `MSG_SELECT_*` 解析当前本地玩家可用的命令、卡片、区域、表示形式或选项，并
  填充 GUI 使用的候选容器；
- 每个消息解析完成后，作用域退出钩子调用 `AgentClient`。因此结构化记录始终
  观察到与界面一致的解析后状态，而不会侵入 `ocgcore`、原始包格式或 Lua 卡片
  脚本。

`STOC_SELECT_HAND` 和 `STOC_SELECT_TP` 不属于 `STOC_GAME_MSG`，分别表示猜拳和
选择先攻/后攻；它们在 LAN 包分发处单独写入采集日志。客户端发送
`CTOS_HAND_RESULT` / `CTOS_TP_RESULT` 前记录实际提交，收到 `STOC_HAND_RESULT` 后记录
双方出拳和本地视角的 `win` / `loss` / `draw`，但不改变原网络包。

导出状态遵循本地玩家视角：公开场面和本方已知卡输出 `id`，对方隐藏信息只输出
数量。每局第一条决策请求输出完整快照，之后仅输出 JSON Patch。当前连锁会随状态
输出，以便 agent 获得已经公开的连锁卡 `id` 和控制者信息。

导出记录使用 `event_id` 表示严格顺序，并使用 `timestamp_unix_ms` 便于排障。
`state_revision` 仅在可见场面变化时递增；`json_patch` 通过
`base_state_revision` 指向前一版本。若当前决策不改变场面，使用
`state_delta.mode: "none"`，状态版本保持不变。

猜拳或先后攻选择会预先建立 `duel_id`，随后 `MSG_START` 复用它并清除旧快照基线；
若没有赛前阶段，`MSG_START` 才创建标识。同一 `duel_id` 的状态版本不会在
`MSG_START` 回退。每次新的赛前阶段都会创建新标识，因此异常结束也不会复用旧局 ID。
远端连接在 `hello_ack` 后也会强制下一条请求为 `snapshot`，确保
服务端无需依赖断线前状态。

所有协议语义值由 `gframe/agent_client/agent_protocol.h` 的 `enum class` 定义并
序列化为固定 ASCII 标识符，例如 `self`、`main_monster`、`idle_command` 和
`special_summon`。解析层不得将 UI 本地化文本写入 JSONL 或 agent 请求。

## v3 的确定信息边界

客户端额外转写 `MSG_HINT`、`MSG_CONFIRM_CARDS`、`MSG_BECOME_TARGET`、
`MSG_CARD_TARGET`、`MSG_CANCEL_TARGET`、`MSG_EQUIP` 和 `MSG_UNEQUIP`。这些字段保留
原始消息含义，不升级为引擎没有声明的因果关系：

- `MSG_BECOME_TARGET` 统一记录为 `cards_indicated`，因为脚本也可用它实现纯 UI 指示；
- `MSG_CARD_TARGET` 表示持续的卡片对象关系，不代表某次发动的效果对象；
- `MSG_HINT/HINT_SELECTMSG` 的值随当前选择消息变化，只作为原始上下文提示；
- `MSG_CONFIRM_CARDS` 提供明确公开的卡片 ID，SDK 知识账本可据此记忆隐藏区已知卡；
- `MSG_MOVE.reason` 同时保留原始位掩码和稳定的原因枚举列表，但标记为非权威辅助证据；
- `MSG_NEW_TURN` / `MSG_NEW_PHASE` 分别生成 `turn_started` / `phase_changed`；
- `MSG_ATTACK`、`MSG_BATTLE`、`MSG_ATTACK_DISABLED` 分别生成 `attack_declared`、
  `battle_snapshot`、`attack_disabled`，同一次攻击通过 `attack_id` 关联。

`MSG_MOVE` 还保留 `engine_code`。当其为 0、但移动来源在客户端移动前确定公开时，客户端
可使用 `ClientCard::code` 补充事件的卡片 ID，并标记
`card.id_provenance: "public_client_cache"`。表侧额外卡组输出 `position: "face_up"`，
并允许使用该公开缓存；里侧额外卡组输出 `position: "hidden"`。该回补不适用于对方手牌、卡组、里侧卡或
叠放卡，不能借机读取隐藏信息。

区域坐标以每个区域内部为基准：额外怪兽区的 `slot_index` 是 0/1，`slot_number` 是
1/2；原始 MZONE sequence 5/6 只放在 `engine_sequence` 中。

`activatable_cards[i]` 与 `activatable_descs[i]` 按索引对应，因此发动候选可以携带
描述 ID、描述文本和描述槽位偏移。槽位偏移不是卡文的①②③。OCG 联网协议没有提供
完整的“结果由哪个效果造成”关联，客户端不做卡片文本推断，交由 agent 在上层完成。

本轮不调用 `ocgapi.h` 的 `query_*` 接口：它们需要本地 `pduel`，不能用于连接远端
OCG 服务器的联网客户端。单人模式与录像模式也不在本轮采集范围内。

完成 `hello_ack` 后，`duel_event` 和 `decision_request` 都会实时进入 Agent TCP 通道；
没有可用连接时仍完整落本地 JSONL。握手进行中的事件使用有界队列暂存。对局边界过滤旧局
入站消息，但不丢弃已排队的上一局终局事件；`inspect_zone` 必须携带当前 `duel_id`。

`MSG_SUMMONING` / `MSG_SPSUMMONING` / `MSG_FLIPSUMMONING` 携带卡片与位置，因此输出
具体的 `summon_attempted`。对应的 `MSG_*SUMMONED` 不携带卡片或批次标识，所以只输出
无卡片归属的 `summon_succeeded`，避免对嵌套或成组召唤作错误关联。

`MSG_BATTLE` 给出双方当时的攻守数值和战斗破坏标志，但它不是完整的伤害步骤终局消息，
因此事件命名为 `battle_snapshot`。后续 LP 变化和卡片移动仍由各自的专用事件表达。

历史日志出现过 `MSG_MOVE.reason` 残留 `draw` 位的情况。客户端不删除原始位，而是增加
`reason_flags_authoritative: false` 与 `reasons_authoritative: false`。上层应优先采用
`cards_drawn`、`summon_attempted`、连锁生命周期和战斗事件，不得仅凭该原因位断言因果。
