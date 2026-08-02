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
选择先攻/后攻；它们在 LAN 包分发处单独写入采集日志。

导出状态遵循本地玩家视角：公开场面和本方已知卡输出 `id`，对方隐藏信息只输出
数量。每局第一条决策请求输出完整快照，之后仅输出 JSON Patch。当前连锁会随状态
输出，以便 agent 获得已经公开的连锁卡 `id` 和控制者信息。
