# 客户端 ⇄ Agent HTTP 契约 v3

## 范围

本契约扩展 [v2 状态契约](agent-http-v2.md)的可见快照、连续事件、状态版本与动作形状，以支持一次决策中的只读客户端查询和动作执行回执。游戏服务端和 CTOS/STOC 不变。正式 Agent 服务只接受 `/v3/*`；现有 v2 确定性测试服务继续按原契约运行，不做静默降级。

客户端仍主动发起所有 HTTP 请求。请求、响应都是 UTF-8 JSON，`schema_version` 为整数 `3`。运行于本机回环地址；决策 API 要求客户端启动时生成并传给独占子进程的高熵 Bearer token，人类只读 API 使用另一令牌。`/view` 只返回无数据的静态页面。请求体、响应体、嵌套深度和连接数须受限。服务端不得通过查询要求客户端暴露本方此刻无权查看的信息。

## 标识与期限

`session_id`、`duel_id`、`prompt_id`、`state_version`、`event_id`、`ack_event_id`、`database_sha256` 沿用 v2。一次决策由 `(session_id, duel_id, prompt_id, state_version)` 唯一标识。服务端签发只在该决策内有效的 `query_id` 和 `action_id`。客户端不能指定或复用这些 ID。

`deadline_unix_ms` 是**整次决策**的绝对截止时间。模型调用、无效意图重试、沙盒和工具、客户端查询以及压缩调用共享它；每轮 HTTP 不得重新计时。客户端从配置的总上限和已确认的本方剩余操作时间中取较短者，并预留提交动作的时间。服务端在期限后不得签发动作；客户端在期限后不得提交动作。客户端提示撤销、人工接管、对局结束或子进程退出时取消在途决策。

## 服务就绪：`GET /v3/ready`

客户端启动独占服务子进程后，以启动时生成的 Bearer token 查询就绪状态。响应包含 `schema_version: 3`、服务启动 nonce 和配置档名。服务只绑定配置的 `127.0.0.1` 端口；端口占用即启动失败。客户端只信任自己启动的进程及其就绪响应，不连接占用端口的其他服务。服务提供独立只读令牌供本机人类视图使用；此令牌不能调用决策接口。

客户端把 `YGOPRO_AGENT_BOOT_TOKEN`、`YGOPRO_AGENT_BOOT_NONCE` 仅交给子进程环境。子进程完成配置、资源、数据库和真实模型能力检查，并成功绑定端口后，向 stdout 写出唯一一行不超过 4 KiB 的 JSON：`schema_version`、`port`、`nonce`、`decision_timeout_ms`。客户端等待最多 60 秒，然后用同一 nonce、端口、档名与期限复核 `/v3/ready`。之后服务只向 stderr 或本地日志输出诊断，不在 stdout 输出第二行。

## 决策：`POST /v3/decision`

请求包含 v2 `/v2/decision` 的字段、快照冻结与可见性规则，`schema_version` 为 `3`，并按下述规则携带 `deck_manifest`。服务器必须先校验并持久接收完整事件前缀、快照和首次牌表，再运行模型。相同身份、版本和请求内容的重传不重复提交状态，也不启动第二次模型运行；内容不同返回冲突。

`deck_manifest` 是首次决策必填的顶层对象，表示客户端本局人工实际提交的本方卡组。它含 `main`、`extra`、`side` 三个数组；数组项为 `{ "card_id": int, "count": int }`，卡片 ID 为正整数、张数为正整数。每个数组按 `card_id` 升序排列，同一数组内不得重复 ID；数组顺序不表示抽取顺序或其他牌序。空数组允许。示例：

```json
"deck_manifest": {
  "main": [{"card_id": 12345678, "count": 3}],
  "extra": [{"card_id": 23456789, "count": 1}],
  "side": []
}
```

客户端在人工选卡组并实际提交后捕获清单。对每个 `(session_id, duel_id)`，服务端只接受并持久保存首次决策中的清单；若首次决策缺少它，返回 `deck_manifest_missing`，不运行模型。客户端收到首个有效决策响应后，后续决策省略该字段；首个响应之前可重传相同清单。已绑定清单在同局服务重启后保留。首次请求原样重传须幂等；同一牌表绑定出现不一致内容或后续试图替换牌表时，返回 `deck_manifest_conflict`。服务端校验清单 ID 存在于本地 `cards.cdb`，并使用请求中的 `database_sha256` 完成既有数据库一致性校验。

服务在首次赛前模型输入中提供从本机 `cards.cdb` 生成的本方主卡组与额外卡组目录，每种卡按 ID、张数、卡名和类型紧凑呈现，不包含效果文本。备牌只持久保存，本期不提供给模型决策。模型可调用 `own_decklist` 重新读取本方目录。牌表目录不是当前抽牌顺序，也不表示各区域当前余量；运行时可见状态仍完全以客户端观察为准。

响应是以下两种之一。`ack_event_id` 只覆盖已持久接收的连续事件前缀。

```json
{
  "schema_version": 3, "kind": "query",
  "session_id": "client-process-id", "duel_id": "one-duel-id",
  "prompt_id": 42, "state_version": 17, "ack_event_id": 8,
  "query_id": "opaque-query-id",
  "query": {"kind": "inspect_zone", "player": 0, "zone": "graveyard"}
}
```

```json
{
  "schema_version": 3, "kind": "action",
  "session_id": "client-process-id", "duel_id": "one-duel-id",
  "prompt_id": 42, "state_version": 17, "ack_event_id": 8,
  "action_id": "opaque-action-id", "reason": "选择通常召唤。",
  "action": {"kind": "choice", "candidate_id": "c0"}
}
```

`action` 沿用 [动作契约](duel-actions.md)，必须来自 `agent_sdk` 对模型语义意图的校验和翻译。客户端仍按 v2 复核会话、提示、版本、候选和参数，再调用原有响应编码。模型不得给出底层游戏协议字节。

服务端响应至多有一个当前阶段。同一决策重传返回目前有效的阶段和相同 `query_id` 或 `action_id`，不重新调用模型。已过期、已取消或已完结的阶段不再签发动作。服务进程重启后不恢复进行到一半的模型运行；客户端交还人工，并在新提示上按持久状态恢复。

## 客户端查询：`POST /v3/query-result`

模型先使用服务端已确认状态镜像。仅当该镜像缺少当前可合法查看的信息时，才允许请求客户端查询。首版查询白名单为：

| `kind` | 参数 | 语义 |
| --- | --- | --- |
| `inspect_zone` | `player` 为 `0` 或 `1`，`zone` 为 v2 已定义区域名 | 读取该区域此刻可见的卡片列表与数量；不可展开的对象仍仅给数量。 |
| `inspect_card` | `instance_id` 为当前场面位置键 | 读取该位置此刻可见、来源可确认的卡片字段。位置键不代表跨区域稳定身份。 |

客户端必须按 v2 可见性白名单重新生成结果，不得直接序列化 `ClientField` 或 `ClientCard`。未观测到的动态字段省略；隐藏身份、牌序、内部脚本状态和原始游戏协议不返回。结果绑定原 `session_id`、`duel_id`、`prompt_id`、`state_version` 和 `query_id`；一条查询只接受一个确定结果。客户端在执行查询前确认原提示仍有效，权限与冻结快照一致；若无法保证，返回错误并交还人工。`not_visible`、`unavailable`、`stale_prompt` 不得转换成猜测值。

```json
{
  "schema_version": 3,
  "session_id": "client-process-id", "duel_id": "one-duel-id",
  "prompt_id": 42, "state_version": 17, "query_id": "opaque-query-id",
  "result": {"kind": "inspect_zone", "zone": {"player": 0, "name": "graveyard", "count": 1,
    "hidden_count": 0, "cards": [{"instance_id": "0:16:0", "controller": 0,
      "location": "graveyard", "sequence": 0, "position": "face_up",
      "known": true, "card_id": 12345678}]}}
}
```

查询结果请求返回新的 `kind: "query"` 或 `kind: "action"` 决策响应，沿用上述身份和确认字段。同一结果原样重传幂等；同一 `query_id` 内容冲突返回错误。服务端同一决策最多等待一条查询；查询额度由配置强制限制。查询结果作为该视角的本次观察事实入服务端日志，但不覆盖客户端决策时冻结的权威快照，也不被偷偷并入下一个版本。

## 动作执行回执：`POST /v3/action-result`

客户端收到动作响应后报告实际提交情况：

```json
{
  "schema_version": 3,
  "session_id": "client-process-id", "duel_id": "one-duel-id",
  "prompt_id": 42, "state_version": 17, "action_id": "opaque-action-id",
  "status": "submitted"
}
```

`status` 为 `submitted`、`stale_prompt` 或 `rejected`。`submitted` 表示客户端已将编码后的响应提交给原有决斗流程，**不保证游戏服务端随后接受或执行**；页面只可显示“客户端已提交”。另外两种状态不得记为已执行。相同回执幂等，冲突回执拒绝。回执不推进场面版本；下一次权威快照和事件仍来自客户端游戏消息。

## 同步、状态及故障

`POST /v3/sync` 与 `POST /v3/status` 沿用 v2 的内容和持久确认语义，仅版本及路径更新。`/v3/status` 只恢复已持久接收的快照版本和事件前缀，不恢复中断的模型执行或旧提示。客户端一旦收到权威 `MSG_WIN`，须立即停止本局待决策动作、取消在途决策请求，并通过 `/v3/sync` 提交 `duel_ended` 事件；不得等待胜利动画、录像保存弹窗或 `STOC_DUEL_END`。服务端持久接收该事件后取消本局模型与工具任务，拒绝此局后续决策及迟到的动作／查询回执；重复终局同步保持幂等。取消不撤销游戏服务端已经接受的动作，也不改写权威胜负结果。

所有错误均不含动作。非 2xx 错误体沿用 v2，补充 `query_not_pending`、`query_conflict`、`action_conflict`、`budget_exhausted`、`provider_unavailable`、`deck_manifest_missing` 和 `deck_manifest_conflict`。期限届满、历史不完整、状态冲突、客户端查询失败和在途执行中断时交还人工。客户端不会因 HTTP 超时执行旧动作；服务端不会因为重传而重复调用模型或重新执行查询工具。

决策预算耗尽返回 HTTP 429，错误体 `error.code` 为 `budget_exhausted`；客户端向人工展示该语义错误码，不能仅显示 HTTP 状态码。该错误不表示决斗协议缺少消息类型，且不得提交任何动作。

## 人类只读接口

人类接口独立于客户端 Bearer token，只监听本机；提供最新已确认状态、分页历史、净差异、模型决策、客户端回执及各自的版本与时间。仅显示该子进程拥有的单方视角。`/v3/sync` 可在两次决策间推进事件但不刷新快照；界面必须分别标示事件截止点与快照版本，不把它们称作逐帧实时场面。
