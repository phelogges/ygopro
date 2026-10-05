# 客户端 ⇄ Agent HTTP 契约 v1

## 传输

客户端向配置的 Agent 地址发送 `POST /v1/decision`，请求与响应均为 UTF-8 JSON，`Content-Type: application/json`。每个客户端同一时刻只允许一个未完成请求。启用局域网访问时使用 `Authorization: Bearer <token>`；默认只连接本机。限制请求/响应体大小、连接与总决策时长，超限视为失败并交还人工。Agent 不直接连接游戏服务端。

## 决策请求

```json
{
  "schema_version": 1,
  "session_id": "client-process-id",
  "duel_id": "duel-id-created-before-opening-choice",
  "prompt_id": 42,
  "database_sha256": "64-character-lowercase-hex",
  "deadline_unix_ms": null,
  "observation": {
    "self_player": 0,
    "turn_player": 0,
    "turn": 1,
    "phase": "main_1",
    "life_points": [8000, 8000],
    "zones": [],
    "events": []
  },
  "prompt": {
    "kind": "idle_command",
    "description": "请选择当前操作",
    "candidates": [
      {
        "id": "c0",
        "kind": "normal_summon",
        "description": "通常召唤手牌中的第 1 张已知卡",
        "card": {"instance_id": "p42-c0", "card_id": 12345678, "controller": 0, "location": "hand", "sequence": 0}
      }
    ],
    "constraints": {}
  }
}
```

`session_id` 属于客户端进程，`duel_id` 在赛前第一次决策前生成，`prompt_id` 在当前对局内单调递增。`candidate.id` 仅在该提示内稳定。`observation` 是当前玩家视角的自包含快照，`events` 是自上次决策以来的已观测事实。未公开卡不得有 `card_id`。卡片的当前位置、数值等动态信息须随实例出现，不能通过卡片数据库查询代替。`description` 用中文；字段和枚举使用固定英文。客户端不发送卡名及效果文本。

`database_sha256` 对客户端实际加载的卡库文件计算。正式 Agent 服务应核对自身数据库，错误时返回 `database_mismatch`。无卡库的第一期确定性测试端须读取同一文件计算哈希，不得盲目回显客户端提供的值。

## 决策响应

```json
{
  "schema_version": 1,
  "session_id": "client-process-id",
  "duel_id": "duel-id-created-before-opening-choice",
  "prompt_id": 42,
  "reason": "选择进行通常召唤。",
  "action": {"kind": "choice", "candidate_id": "c0"}
}
```

动作只引用当前提示提供的 ID。`reason` 不参与动作解释，也不会发送给游戏服务端。`agent_sdk` 生成此结构并验证候选与约束；客户端收到后再次核对会话、提示、候选与参数，然后本地编码为原有 CTOS 响应。客户端不得接受原始 CTOS 整数、字节数组或自由文本作为动作。

组合选择使用下列 `action.kind`：

- `choice`：一个候选 ID，适用于命令、是/否、选项、连锁、位置、宣言数字等。
- `select_cards`：`candidate_ids` 数组，适用于一次完成的选卡、解放、合计及排序；排序按数组顺序表达。
- `select_step`：一个候选 ID，适用于可反复选择/撤销的 `UNSELECT_CARD`。
- `select_places`：`places` 数组，元素含 `controller`、`location`、`sequence`，适用于区域选择。
- `distribute_counters`：`allocations` 数组，元素含候选 ID 和非负数量。
- `announce_card`：一个 `card_id`；SDK 和客户端必须校验声明过滤条件。

所有组合动作的范围、唯一性、数量及 SUM/解放权重等约束由 SDK 和客户端分别验证。无法可靠验证时返回错误或 `unsupported_prompt`，不得猜测响应。

## 错误与重试

Agent 服务可返回非 2xx 状态及 JSON：

```json
{"schema_version":1,"error":{"code":"unsupported_prompt","message":"该提示尚未支持"}}
```

错误码至少包含 `unsupported_prompt`、`invalid_intent`、`database_mismatch`、`internal_error`。客户端本地错误包括 `stale_prompt`、`invalid_action`、`timeout`、`transport_error`。第一期错误均保留人工操作入口。HTTP 传输失败不得对同一提示自动重试以免重复提交。`MSG_RETRY` 是游戏服务端要求重新选择，必须生成新 `prompt_id`。

## 版本

`schema_version` 对请求与响应必填。客户端拒绝不支持的主版本。新增可选字段不改变已定义字段含义；动作编码与游戏二进制协议的映射只存在客户端实现和 `docs/contracts/duel-actions.md` 中。
