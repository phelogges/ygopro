# 客户端游戏消息覆盖审计

> 状态：现行设计与待处理清单；截至 2026-10-11。事件字段以 [Agent HTTP v3](../contracts/agent-http-v3.md)及其继承的[观测事件契约](../contracts/agent-http-v2.md#观测事件)为准。机器清单在 [`tools/agent-message-coverage.json`](../../tools/agent-message-coverage.json)。

## 为什么需要独立分类

`ocgcore` 将游戏消息编号写入客户端协议，原生 GUI 在 `gframe/duelclient.cpp` 更新场面和动画。Agent 另在 `gframe/agent_client/agent_controller.cpp` 将同一消息转为本方可见事件；原生 GUI 能处理不等于 Agent 已处理。瞬时展示、洗切、关系变化也不能只靠后续快照恢复。未解析的消息保持 `history_complete=false`，拒绝自动决策，不将原始包交给模型。

`MSG_SHUFFLE_SET_CARD`（36）曾由原生客户端处理，但未进入 Agent 事件转换。这次双端录制暴露缺口后已补安全事件。随后对 14 类当前单局消息逐类核对引擎发送格式、原生 GUI 处理和隐藏信息边界，并增加结构化解析。可独立测试的游戏事件解析集中在 `gframe/agent_client/game_event_codec.h`，由 `AgentController::RecordEvent` 与既有事件分支共同调用；不按“此前遗漏”建立永久分类。`MSG_HAND_RES` 也可能由卡片效果在对局中触发，不能只当作赛前消息。静态检查 `python3 tools/check-agent-message-coverage.py` 从原生 `case MSG_*` 提取消息名，并要求每个名字恰好归入 Agent 已解析、明确无需事件或待处理。检查已加入 CTest，防止上游新增原生消息时无声遗漏。它不能证明已解析字段的可见性或事件语义正确，仍需双视角录制与测试。

## 当前待处理

| 范围 | 消息 | 审核结论 |
| --- | --- | --- |
| 当前范围外 | `MATCH_KILL`、`TAG_SWAP`、`RELOAD_FIELD` | 分别涉及三局赛、双打、调试或残局场面重建；若收到仍失败关闭，尤其不能忽略场面重建。 |
| 旧兼容 | `UNEQUIP` | 原生 GUI 保留分支；引擎当前定义已注释且未发现发送处。若实际收到仍失败关闭。 |

以上共 4 类，原生客户端的 86 类消息中有 55 类已解析、27 类明确无需事件。新增 14 类已有字节级和服务端结构校验；尚缺逐类真实双视角录制，以确认对局中的事件顺序与隐藏信息处理。后续任务见[路线图](../roadmap.md)。
