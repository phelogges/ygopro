# ygopro-agent-sdk

`ygopro-agent-sdk` 是面向 agent 项目的 Python 3.12 SDK。它处理 YGOPro 客户端
`agent_client` 输出的 v2/v3 JSON/TCP 协议，不解析 YGOPro 的原始二进制对局包。

## 能力

- 增量 TCP 长度帧解码与编码；
- `hello` / `hello_ack` 和 `decision_request` 基础校验；
- 按 `(session_id, duel_id)` 维护 `snapshot`、RFC 6902 `json_patch`、`none` 状态；
- 校验 `event_id`、`state_revision` 与 `base_state_revision`；
- 解析引擎观测的 `duel_event`，并保留其原始消息证据；
- 解析 v3 的发动候选描述元数据和选择提示原始值；
- 用 `KnowledgeLedger` 维护 `MSG_CONFIRM_CARDS` 等明确观测到的隐藏区卡片知识，
  保留同名卡数量，并在洗切后清除槽位而不凭空遗忘已经公开的卡片身份；若随后有身份
  未知的卡离开该隐藏区，则这些身份转入 `possible_card_counts()`，不再作为确定位置报告；
- 归约 `cards_drawn`：已知抽卡从牌组知识转入手牌，无编号槽位的同名卡仍分别计数；
  未知抽卡不猜测卡片 ID，并将可能受影响的牌组确定知识降级为 `possible_card_counts()`；
- 分开提供“最近一次决策携带的场面状态”和“事实事件的轻量观测投影”；
- 将合法 `choice_id` 或选卡下标封装为 `action` 回复；
- 重放客户端 JSONL 采集日志。

## 安装与构建

开发环境：

```powershell
cd ygo_agent_sdk
uv sync --group dev
uv run ruff check .
uv run pyright src
uv run python -m unittest discover -s tests -v
```

构建发布包：

```powershell
uv build
```

生成的 wheel 与源码包位于 `dist/`，可由其他项目使用：

```powershell
uv add path/to/ygopro_agent_sdk/dist/ygopro_agent_sdk-0.1.0-py3-none-any.whl
```

## 使用示例

```python
from ygopro_agent_sdk import ProtocolSession

session = ProtocolSession()
request = session.ingest_message(client_message)
assert request is not None

# 策略只在当前请求的 choices 中选取。
reply = request.choose(request.choices[0].id)
wire_bytes = reply.to_frame()

# 这是最近一次 decision_request 携带的状态；它不会随后续事实事件自动变化。
decision_state = session.state_at_last_decision(request.session_id, request.duel_id)

# 这只是由明确事实事件归约出的局部观测，目前包含已观测 LP 与终局信息。
# 它不是完整场面快照，字段缺失代表尚未被该归约器观测到。
observed = session.observed_state_for(request.session_id, request.duel_id)
```

`choose()` / `choose_cards()` 生成的 action 自动带上请求的 `session_id` 与 `duel_id`，
供客户端拒绝跨会话或跨对局响应。

`state_for()` 为兼容旧代码而保留，语义与 `state_at_last_decision()` 完全相同。它返回最近
一次 `decision_request` 应用状态增量后的快照，不是对局当前状态。决策之后发生的
`life_points_changed` 和 `duel_ended` 可通过 `observed_state_for()` 查看；该接口刻意只提供
少量明确事实，不会伪装成完整、实时的场面状态。

断线重连后客户端会发送新的 `snapshot`；SDK 以该快照替换该局已有状态。策略不应
自行计算 YGOPro 的内部整数响应，也不应访问隐藏的对手信息。

SDK 的知识账本只保存客户端明确观测到的事实。`remember_card` / `forget_card` 用于
agent 自己维护推理结论，并不把这些结论伪装成引擎事件。SDK 不推断效果编号；cost、素材
和结算关系均不由 SDK 派生。`observations()` 保留完整公开事件封套，包括事件 ID、时间、
查看上下文和引擎证据，便于 agent 自行审计和推理。
