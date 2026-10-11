# 决策动作与现有游戏协议映射

> 状态：现行语义动作映射，适用于正式 [HTTP v3](agent-http-v3.md) 和确定性测试服务的动作校验。本页不定义 HTTP 信封或场景 YAML 版本。

本清单源于第一期动作编解码，并继续约束现行 Agent 动作。游戏服务端协议保持不变。所有候选下标均是服务端消息中的原始顺序；UI 可能排序显示卡片，但不得改变动作编码下标。每一种消息必须有正向解析、动作验证、逆向编码和往返夹具。

| 消息 | 语义动作 | 原有响应 | 关键约束 |
| --- | --- | --- | --- |
| `STOC_SELECT_HAND` | `rock/scissors/paper` | `CTOS_HAND_RESULT` | 线值 2/1/3 |
| `STOC_SELECT_TP` | `go_first/go_second` | `CTOS_TP_RESULT` | 与现有 UI 线值一致 |
| `MSG_SELECT_BATTLECMD` | 攻击、发动、M2、结束 | `CTOS_RESPONSE` i32 | 阶段动作仅在服务端允许时加入 |
| `MSG_SELECT_IDLECMD` | 召唤、特召、转表示、盖放、发动、BP、结束、洗手 | i32 | 每个发动效果是独立候选 |
| `MSG_SELECT_EFFECTYN`、`MSG_SELECT_YESNO` | 接受/拒绝 | i32 0/1 | 仅当前提示 |
| `MSG_SELECT_OPTION` | 选择选项 | i32 索引 | 原始选项顺序；候选文字由客户端本地解析，`description_id` 保留 |
| `MSG_SELECT_CARD` | 多选或取消 | bytes `[count,index...]` / i32 -1 | 数量、唯一性、可取消 |
| `MSG_SELECT_UNSELECT_CARD` | 单步选/撤销、完成/取消 | bytes `[1,index]` / i32 -1 | 每步产生新提示 |
| `MSG_SELECT_CHAIN` | 发动或放弃 | i32 索引/-1 | 强制连锁不可放弃 |
| `MSG_SELECT_PLACE`、`MSG_SELECT_DISFIELD` | 选择区域 | bytes `controller,location,sequence` | 区域掩码、数量、控制者映射 |
| `MSG_SELECT_POSITION` | 选择表示形式 | i32 1/2/4/8 | 必须是允许位 |
| `MSG_SELECT_TRIBUTE` | 选择解放卡 | bytes `[count,index...]` / i32 -1 | 解放权重、数量、可取消 |
| `MSG_SELECT_COUNTER` | 分配指示物 | 每候选 u16 数组 | 总数与上限 |
| `MSG_SELECT_SUM` | 选择合计素材 | bytes 必选占位及候选索引 | 精确/至少和、双取值、必选项 |
| `MSG_SORT_CARD` | 排序或默认 | 每原始候选最终次序 bytes / i32 -1 | 必须为完整排列 |
| `MSG_ROCK_PAPER_SCISSORS` | 石头/剪刀/布 | i32 2/1/3 | 不同于赛前 CTOS 类型 |
| `MSG_ANNOUNCE_RACE`、`MSG_ANNOUNCE_ATTRIB` | 宣言种族/属性 | i32 位掩码 | 选择数与允许位 |
| `MSG_ANNOUNCE_CARD` | 宣言卡片 ID | i32 卡片密码 | 过滤 opcode 与卡库 |
| `MSG_ANNOUNCE_NUMBER` | 宣言数字 | i32 候选索引 | 不是数字值 |

`MSG_RETRY` 不产生新动作类型：撤销上一提示，重新解析上一决策并分配新提示 ID。需要 Agent 决策的提示由适配层统一提交并抑制第二次提交；没有可发动候选的 `MSG_SELECT_CHAIN` 响应窗口由客户端自动放弃，不生成 Agent 决策或场景步骤，详见[场景契约](agent-scenario-v1.md)。`MSG_SELECT_POSITION` 只有一个允许位时现有解析仅设置整数响应，适配层必须保证实际发送。
