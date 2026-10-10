# Agent 决斗工具契约 v1

> 状态：现行正式 Agent 服务的共用工具语义契约。适用于 Pydantic AI 与 Codex 两种后端；客户端通信仍以 [HTTP v3](agent-http-v3.md) 为准。旧版认知笔记工具见[历史契约](agent-knowledge-notes-v1.md)。

## 边界与接入

每次真实决策建立一个 `DecisionDeps`，绑定本方 `session_id`、`duel_id`、已确认 `state_version`、事件前缀、总期限和预算。`agent_server/duel_tools.py` 的 `DuelTools` 执行下表中的业务方法。Pydantic AI 在 `model_agent.py` 用 `@agent.tool` 注册工具；Codex 经单个 `ygopro_duel` MCP stdio 服务公布工具，再由 `codex_mcp_bridge.py` 按当前决策转发至同一个 `DuelTools`。两种接入层分别维护模型可见的名称、参数类型和说明，不能仅靠系统指令注册工具。

工具执行层检查期限、计入宿主工具尝试，读取当前决策绑定的资源与状态。两端入口均须检查参数，服务端及客户端仍各自执行可见性和动作校验。工具返回的信息不授权模型直接写游戏协议字节，也不修改权威镜像。修改共用能力时须核对两端接入层的参数、描述、结果、预算及测试。

## 共用工具

| 工具 | 参数 | 当前执行语义 |
| --- | --- | --- |
| `rulebook_index` | 无 | 列出本地 OCG 规则书可用主题。 |
| `rulebook_section` | `section: str` | 读取一个白名单规则书章节。 |
| `card_by_id` | `card_id: int` | 从本地 `cards.cdb` 读取一张卡的公开资料。 |
| `cards_by_ids` | `card_ids: list[int]` | 批量读取不同 ID 的完整资料，按输入顺序返回；数量受 `card_lookup_batch_size` 配置限制，默认最多 12 个。记录批次大小、返回字节数和耗时。 |
| `search_cards` | `keyword: str`, 可选 `limit: int = 30`, `offset: int = 0` | 搜索卡片文本，分页返回匹配 ID。 |
| `own_decklist` | 无 | 读取本局已提交主卡组与额外卡组的 ID、张数、卡名和类型目录；不表示抽牌顺序或当前剩余量。 |
| `current_state` | 无 | 读取本决策 `state_version` 对应的完整、本方可见、已确认快照。 |
| `zone_state` | `player: int`, `zone: str` | 从同一快照读取一区的数量与可见卡片；隐藏身份不展开。区域名称沿用 [HTTP v2 状态契约](agent-http-v2.md#可见状态白名单)。 |
| `card_state` | `instance_id: str` | 读取当前可见位置键对应的单卡；位置键不是跨区域稳定实体 ID。 |
| `event_history` | 可选 `after_event_id: int = 0`, `limit: int = 50` | 分页读取本方已确认事件；从当前决策所见 `state_version` 截止，单页至多返回 100 条。 |
| `calculate` | `operation: add|subtract|multiply|divide|compare`, `left`, `right` | 共用的受限十进制运算；输入为有限数字或数字字符串、单个操作数文本不超过 80 字符且绝对值不超过十亿。除以零、越界或未知操作报错；结果为十进制字符串，比较返回 `-1`、`0` 或 `1`。 |

规则书只读取发布根目录 `.agents/skills/ocg-rulebook` 的白名单资源；卡片工具使用 `.agents/skills/ygo-card-db` 的实现及发布根目录 `cards.cdb`。`current_state`、`zone_state`、`card_state` 和 `event_history` 从同一已确认镜像读取，供只收到增量输入的 Agent 按需查询。历史隐藏信息通过有序事件回查，由 Agent 结合当前状态重新判断；旧版笔记记录只在人类视图中作为历史资料显示，不再作为独立字段注入新决策。继续旧对局时，两种后端均丢弃缺少当前工具集版本的旧模型会话，改从最新已确认快照建立上下文，避免历史对话中的旧笔记流入新决策。HTTP v3 的客户端 `inspect_zone`、`inspect_card` 往返仍保留作协议兼容和诊断；服务端要求其结果与冻结快照完全一致，因此 Pydantic AI、CodeMode 和 Codex MCP 均不向模型暴露这两个重复查询工具。

Pydantic AI 的本地 Monty CodeMode 允许在受限 Python 表达式中直接计算，亦可调用上表中的只读工具及 `calculate`。Codex 通过 MCP 使用 `calculate`，不开放任意 Python 执行。两后端的 `calculate` 走同一 `DuelTools` 十进制实现；Monty 表达式是额外的框架能力，不是另一套业务计算规则。

## 失败与版本

超时和预算耗尽不得产生动作；超过宿主工具次数返回 `budget_exhausted`。保留的客户端查询协议仍受独立次数限制。无效区域、不可见位置、无效数值或查询失败保留错误语义，不补造卡片身份、规则因果或查询结果。共用工具的业务语义如需变更，先更新本契约与相关 [HTTP](agent-http-v3.md) 契约，再验证 Pydantic AI 与 Codex 两种入口。
