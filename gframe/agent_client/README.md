# agent_client：远端 AI 协议与本地采集

`agent_client` 将已经由客户端解析完成的对局状态转换为 UTF-8 JSON。它与
YGOPro 的对局网络协议、GUI 和 `ocgcore` 隔离：模块只观察 `ClientField`，并在
需要本地玩家作答时生成结构化请求。

## 当前采集模式

没有运行 agent 时也可以使用。将下列配置写入 `system.conf`：

```ini
agent_enabled = 1
agent_host = 127.0.0.1
agent_port = 7450
agent_timeout_ms = 15000
agent_log_path = agent-log.jsonl
```

每次本地决策都会追加一行 JSONL 到 `agent_log_path`。无服务端连接时，记录的
`direction` 为 `"local"`，客户端不会等待回复或改变人工操作；这是当前收集
样本、压缩上下文的推荐方式。猜拳与先攻/后攻选择同样会记录。

首条对局状态使用：

```json
{"mode":"snapshot","data":{}}
```

后续记录使用 RFC 6902 JSON Patch：

```json
{"mode":"json_patch","data":[{"op":"replace","path":"/players/1/hand/count","value":7}]}
```

因此读取日志时应从最近的 `snapshot` 开始，依次应用后续 `json_patch`。

## 状态与可见性

- 已知卡以 `id`（8 位密码）表示，并携带区域、序号、表示形式和 `known`。
- 我方手牌、墓地、除外区和额外卡组可发送已知 `id`；对方隐藏手牌、卡组和
  额外卡组只发送数量。
- 场上公开卡、可选卡、主要/战斗阶段候选动作和当前连锁会携带卡片引用。
- 选区消息提供 `zone_choices`；选卡消息提供 `card_choices`。这些候选集是
  agent 唯一允许选择的范围。

`integer_choices` 中的 `value` 是现有引擎需要的整数响应，而非卡片密码。例如
主要阶段的命令编码为 `(候选索引 << 16) + 动作类型`；`65537` 表示对索引 1 的
候选执行特殊召唤。关联卡片会位于同一候选项的 `card.id`。当前协议保留该值以
便于调试和客户端回放；agent 侧应优先依据 `label` 与 `card` 决策。

## 远端连接协议（预留）

启用远端 agent 后，客户端使用 TCP 连接 `agent_host:agent_port`。每帧由 4 字节
大端无符号长度和一段 UTF-8 JSON 构成。连接建立后客户端先发送：

```json
{"type":"hello","protocol":1,"language":"zh-CN","client":"ygopro"}
```

agent 必须回复 `{"type":"hello_ack"}`。随后客户端发送：

```json
{
  "type":"decision_request",
  "request_id":17,
  "revision":17,
  "summary":"请为我方选择卡片，只能从下列合法选项中选择。",
  "state_delta":{},
  "decision":{}
}
```

当前接收的动作格式为：

- `{"kind":"integer","value":N}`：选择 `integer_choices` 中存在的响应值；
- `{"kind":"cards","indices":[...]}`：选择 `card_choices` 中的下标；
- `{"kind":"cancel"}`：仅限当前消息允许取消时。

客户端会验证 `request_id`、当前消息、候选值与选卡数量，然后才复用
`SetResponseI` / `SetResponseB` / `SendResponse`。超时、断开、过期或非法回复会
放弃 AI 控制并保留当前人工提示。
