# Agent 可观测性契约 v1

## 范围与授权

本契约补充[客户端与 Agent HTTP v3 契约](agent-http-v3.md)的人类视图，不改变 `/v3/decision`、查询、动作回执、客户端 GUI 或游戏联网协议。服务只绑定 `127.0.0.1`。`GET /view` 和同源静态资源无需授权且不包含对局数据、令牌或密钥；所有 `/v3/view/*` 数据 GET 请求都要求该配置档 `.agents/data/<profile>/viewer-token` 对应的 `Authorization: Bearer <token>`。该令牌只能读，不能调用决策接口或删除数据。令牌不得放在 URL、浏览器长期存储、页面日志或导出文件中。前端使用原生 `fetch` 发送授权头并解析 SSE，因此无需 Node 或浏览器原生 `EventSource` 的授权限制。

配置档 `config`、`host`、`guest` 分别持有独立数据库和查看令牌，默认目录为 `.agents/data/<profile>/`。每个服务只暴露其配置档数据库中的本方视角；请求参数无权选择其他档。响应使用 UTF-8；查看 API 的 JSON 顶层包含 `schema_version: 3`，单局导出文件自身使用 `schema_version: 1`。错误返回 JSON `error.code` 和 `error.message`，不得在错误中回显敏感输入。

## 标识与事件

时间线按 `(session_id, duel_id)` 选择单个本方对局。`turn_id` 为 `"<prompt_id>:<state_version>"`，仅在同一对局中唯一；同一游戏提示内的每次模型响应都有不同的 `response_id`。每条已提交的轨迹事件采用下列结构：

```json
{
  "id": 1204,
  "turn_id": "42:17",
  "response_id": "42:17:r3",
  "kind": "content_delta",
  "payload": {"source": "provider_reasoning", "form": "summary", "text": "先检查墓地。"},
  "created_unix_ms": 1791368320123
}
```

`session_id` 与 `duel_id` 由请求选定，不在每条 trace 对象中重复。`id` 是配置档数据库内严格递增的持久游标，单个对局内事件按 `id` 呈现；删除造成的 ID 缺口合法，ID 不重用。对局级事件以空字符串表示无 `turn_id`，`response_id` 可以为 `null`。事件追加后不可原地修改；文本片段、补充状态和中断标记各占新事件。最少支持以下 `kind`：

| `kind` | 作用 |
| --- | --- |
| `prompt_received` | 提示到达、快照版本、事件范围与净差异的安全摘要。 |
| `model_request_started`、`model_response_started`、`model_response_finished` | Agent 本轮运行开始，以及 SDK 可观察到的各条响应内容开始和完成；逐次供应商请求以 `provider_request_*` 标识。 |
| `content_delta` | 实际收到的推理内容或普通输出片段；`payload.source` 为 `provider_reasoning` 或 `assistant_text`。前者的 `payload.form` 为 `summary` 或 `text`，如实表示供应商返回内容的形态，不承诺原始思维链。 |
| `model_tool_call`、`tool_started`、`tool_finished` | 模型请求工具、宿主开始执行及其安全结果或错误，绑定对应响应。 |
| `output_validated`、`model_decision`、`action_issued` | 结构化输出校验、模型语义意图与说明、签发给客户端的动作。 |
| `client_query_requested`、`client_query_result`、`action_receipt` | 客户端只读查询的请求和结果、动作提交回执。 |
| `decision_failed`、`decision_interrupted`、`duel_finished` | 整次决策失败、中断或对局终结。 |

### 耗时与用量事件

`provider_request_started` 与 `provider_request_finished` 按 `request_number` 配对，属于决策轮而非某条输出消息；后者包含 `duration_ms`、`status`、`first_event_ms`（可能为 `null`）、`first_text_seen`，以及供应商可得时的 `usage`。`usage` 使用 `input_count`、`output_count`、`cached_input_count`、`reasoning_count`；缺失的供应商用量不得根据文本长度估算。`provider_first_text` 仅在第一次收到可读正文或推理内容时出现，含 `source` 与相对请求发起的 `elapsed_ms`。首个流事件与首段可读内容是不同指标，前者包含 SDK 到消费者的交付时间。

`tool_finished`、`output_validated`、`client_query_timing`、`intent_validation_timing`、`model_run_timing`、`decision_timing` 记录各自 `duration_ms`；`action_issued`、`decision_failed`、`decision_interrupted` 的 `duration_ms` 是从提示建立到该终态的总耗时。计时使用单调时钟，事件时间戳仍用墙上时间。错误的供应商请求保留 `status=error` 和异常类名，不回显请求、密钥或认证头。`model_request_started` 记录摘要和思考强度的配置值与实际请求值；`decision_timing` 还记录模型请求次数、非法意图次数、宿主工具调用与客户端查询次数。`reasoning_forms_returned` 只列实际收到的 `summary` 或 `text`，空列表表示没有可读推理。启动探测计时单独写入服务进程诊断日志，不属于对局轨迹。SDK 内部的 HTTP 自动重试如果没有独立暴露，包含在同一次供应商请求耗时中，不伪报重试次数。

服务在产生提示、模型请求、工具调用、结果、错误、动作和回执时及时提交事件。流式文本可小批量提交；只有已提交片段可通过分页或 SSE 看见。工具参数及结构化字段的单个字符串最多保留 16384 字符，列表最多 100 项、对象最多 100 个字段、嵌套最多 16 层；超限处显式标注截断。模型输出文本分片持续保存，不静默丢弃超长片段。`model_response_started` 不等于动作已提交；`action_receipt` 的 `submitted` 仅表示客户端已向既有决斗流程提交。进程重启时，未终结的决策呈现为 `decision_interrupted`，已持久片段保留，不恢复模型栈或补造输出。端点未提供推理内容时，页面显示“未提供”，不可把 `model_decision` 中的理由当成供应商推理。

## 时间线与实时流

`GET /v3/view/duels` 列出当前配置档有已确认操作的对局，按最近活动时间降序排列。每项包含 `session_id`、`duel_id`、`state_version`、`ack_event_id`、`started_unix_ms`、`last_activity_unix_ms` 和 `status`。两个时间都是本档持久操作及轨迹的最早、最晚写入时间（Unix 毫秒），不是游戏内回合时间。`status` 仅有 `finished` 和 `unconfirmed`：前者必须存在已提交的 `duel_finished` 事件；后者表示尚无权威结束记录，不能据此断言对局仍在线。页面默认选择最近活动的一局，显示开始与最近活动时间、状态、短 ID，并支持按完整会话或对局 ID 搜索及时间排序；完整 ID 仍用于选择和请求。

`GET /v3/view/timeline?session_id=...&duel_id=...&after_id=0&limit=100` 返回严格按 `id` 升序排列的事件。`after_id` 为非负整数、排他游标；`limit` 为 1–1000，默认 100。响应示例：

```json
{
  "schema_version": 3,
  "traces": [],
  "next_id": 1204
}
```

若本页为空，`next_id` 保持请求的 `after_id`；否则等于本页最后一条 trace 的 `id`。收到满页时继续以 `next_id` 查询，直到返回不足 `limit` 条。端点只读取该档中匹配的对局；未知对局返回 404。一次页面重连先分页补齐，再建立流。

`GET /v3/view/stream?session_id=...&duel_id=...&after_id=1204` 以 `text/event-stream` 发送相同事件，SSE `id` 等于事件 `id`，`event: trace`，`data` 为上面的单条事件 JSON。必须带 viewer Bearer；服务先回放游标后的已提交事件，再持续发送新事件，回放与订阅之间不能漏事件。支持 `Last-Event-ID` 作为重连游标；同时给出 `after_id` 时，以较大的已确认游标为准，客户端再以事件 ID 去重。定期发送无数据心跳。慢客户端达到服务器缓冲上限时断开，客户端按最后成功解析的 ID 重连；流断开不影响决策。SSE 不承诺逐 token 交付，展示延迟取决于文本持久化批次。

页面以游戏提示为大轮、以模型响应为消息组织时间线，工具调用和结果附在触发它的消息下。每条消息可展开安全原始字段、耗时、错误及校验结果。独立场面/历史页签继续使用 v3 已确认状态接口，并分别标示快照版本、事件截止点和更新时间。

## 卡名、导出与保留

`GET /v3/view/cards?ids=12345678,23456789` 在本机发布根目录 `cards.cdb` 中补充显示名。`ids` 为逗号分隔的十进制卡片 ID，最多 100 个；无匹配项不出现在 `cards` 映射中。响应形如 `{"schema_version":3,"cards":{"12345678":"卡名"}}`，不以卡名替代时间线或权威状态中的 ID，也不改变模型输入。页面不得向外部卡片服务请求数据。

`GET /v3/view/export?session_id=...&duel_id=...` 返回该档单局的 JSON 下载，顶层字段为 `schema_version: 1`、`session_id`、`duel_id`、`status`、`observation`、`complete`、`events`、`traces`、`records`。其中 `status` 给出当前已确认版本，`observation` 是最近已确认可见状态或 `null`，三个数组按各自持久 ID 顺序输出；`traces` 包含实际收到的可显示推理内容。导出再次执行同一字段白名单和大小限制；不得包含 API 密钥、启动/查看令牌、请求认证头、加密推理、签名或供应商内部扩展。未知对局返回 404。正在进行中的对局可导出已提交前缀，标记 `complete: false`，不得暗示后续事实已发生。

自动清理参数默认 `retention_days=30`、`max_bytes=2147483648`（2 GiB），由 Agent 配置管理，按配置档单独执行。`max_bytes` 统计数据库四类持久记录中 `payload` 的**逻辑字节数**，不是 SQLite 文件实际占用、WAL 大小或发布包大小。仅删除已确认结束的对局；先删超过期限的，再在超过逻辑容量时按结束时间从早到晚清理。进行中及结束状态不确定的对局不参与自动清理；即使活跃对局单独超过上限，也必须保留。手动删除使用本机命令 `agent-server --delete-duel --config <profile> --session-id <id> --duel-id <id>`，只允许删除该档已结束对局；确认身份和目标后在单一事务中删除该局状态、记录与轨迹。**不提供 HTTP DELETE 接口**，viewer Bearer 始终只读。

## 历史查看与故障语义

`agent-server --view-only --config <profile> --port <port>` 只打开对应配置档的本机查看页面和只读 API，不启动模型、不连接客户端、不执行清理或决策。查看端口必须显式指定；被占用时报错，不自动换端口。旧版根目录数据库与查看入口已移除。

对局或事件已被清理时，分页与 SSE 返回 404，而非填补缺失历史。授权失败返回 401；非法游标、过大页数或卡片列表返回 400；只读数据库损坏时返回错误并标注不可用，不伪造空结果。页面收到流错误时保留已显示消息，提示连接状态，并从最后一个已提交事件 ID 尝试补拉。正在进行的对局异常退出时，页面显示未完成响应与最后持久时间，不把超时、模型中断或 `submitted` 记为胜负结果。

## 验收

使用模拟流式 Responses 端点验证多次响应、推理摘要片段、无摘要、工具往返、中断与重连后的顺序和去重；用恶意扩展字段验证白名单。覆盖 host/guest 令牌与数据库交叉访问、隐藏信息、导出、卡名、保留和手动删除；以独立发布包运行静态页面和 `--view-only`。真实供应商推理摘要的有无与粒度需在真实端点接入后另行记录，离线测试不能替代。
