# 客户端执行用户与 agent 动作

人工 GUI 最终调用 `DuelClient::SetResponseI` 或 `SetResponseB`，然后调用
`DuelClient::SendResponse`。整数/字节响应均为 YGOPro 内部实现细节，不能成为 agent 的
稳定动作接口；它们只允许在提交后的审计事件中原样保留。

联网赛前的猜拳和先后攻按钮不经过 `SendResponse()`，而是分别发送
`CTOS_HAND_RESULT` 和 `CTOS_TP_RESULT`。客户端在原发送点旁增加只读审计钩子，将语义化
动作、原始值和赛前 `request_id` 记录为 `decision_submitted`，不改变按钮行为或服务器协议。
猜拳原始值固定解释为 `1=scissors`、`2=rock`、`3=paper`。

agent 协议使用 `agent_protocol.h` 的强类型枚举。客户端向每个合法动作分配当前请求
范围内唯一的 `choice.id`，并输出 `action` 枚举（如 `normal_summon`、`activate`、
`pass_chain`）和可选的卡片引用。agent 应答：

```json
{"type":"action","duel_id":"...","request_id":17,"action":{"kind":"choice","choice_id":3}}
```

`AgentClient::Poll` 验证请求仍有效且 `choice_id` 属于当前候选集，然后在内部查表得到
引擎响应并走同一条 `SetResponse*` / `SendResponse` 路径。选卡请求仍使用
`{"kind":"cards","indices":[...]}`，客户端验证唯一性、范围和最小/最大数量。

人工或 agent 的响应最终经过 `SendResponse()` 时，客户端使用独立的提交上下文生成
`decision_submitted`。该上下文不会因 capture-only 模式清理待服务端请求而丢失：

- 可与原请求匹配时写出 `matched: true`、`request_id` 和 `decision_kind`；
- 整数响应能在当前候选表中查到时写出 `choice_id` 与语义化 `action`；
- 选卡响应能完整解码时写出 `selected_indices` 与当时的 `selected_cards`；
- 放置、计数器、排序或宣言等尚无稳定枚举映射的响应只保留匹配信息和
  `response_bytes`，不伪造动作语义。

发动类候选可包含 `effect_candidate`，用于向 agent 提供引擎已经给出的描述 ID、
本地化描述文本、描述槽位偏移和候选标志。`description_offset` 只用于稳定地区分同一卡的
多个描述槽位，不代表卡文印刷的①②③。客户端也不把候选描述进一步解释为后续移动、
支付或召唤的原因；agent 需要结合卡片文本和事件流自行推理。

超时、断连、过期或非法动作不会发送响应，并交还当前人工提示。`integer` 动作格式
只用于调试兼容，正式 agent 不得使用。

Python SDK 生成的 v3 action 同时携带 `session_id` 和 `duel_id`。客户端在执行前校验
当前对局与 `request_id`；`inspect_zone` tool call 也必须携带当前 `duel_id`，避免跨局执行。
