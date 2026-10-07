# agent_sdk

项目内的 Python 3.12 决策契约翻译包，运行时仅使用标准库。负责校验 v1/v2 客户端请求、匹配当前提示候选、把结构化意图转换为语义动作；v2 还提供本方可见状态、事件确认与快照差异的确定性处理。Agent 推理与正式服务框架由调用方实现。契约见 [HTTP v2](../docs/contracts/agent-http-v2.md) 和 [状态处理设计](../docs/design/agent-state-v2.md)。

本地 YAML 场景执行器使用可选的 `scenario` 依赖组（PyYAML）；基础翻译包和正式客户端不需要它。场景格式见 [场景契约](../docs/contracts/agent-scenario-v1.md)。

```python
from agent_sdk import parse_request, build_response

request = parse_request(request_json)
response = build_response(
    request,
    {"kind": "choice", "selector": {"kind": "normal_summon", "instance_id": "p42-c0"}},
    reason="选择通常召唤。",
)
```

## 接口

- `parse_request(str | bytes | dict) -> DecisionRequest`：校验版本、关联字段、SHA256 格式、观测基础字段、卡实例和候选唯一性，复制输入。SDK 不拥有数据库，调用方须独立核对实际卡库哈希。
- `match_candidates(request, selector) -> list[str]`：按 id/kind 或 card_id/instance_id/controller/location/sequence 精确匹配。返回全部匹配，避免相同卡片密码导致误选。
- `translate_intent(request, intent) -> dict`：支持契约中的动作结构；choice/select_step 额外支持 selector，必须恰好匹配一个候选。
- `validate_action(request, action) -> dict`：验证提示类型、候选范围、唯一性和组合约束，返回独立副本。
- `build_response(request, intent, reason) -> dict`：复制关联字段并生成响应。
- `validate_response(request, response) -> dict`：校验版本/会话/对局/提示是否完全匹配，重新校验动作。
- `ContractError` 表示无效数据；`UnsupportedPrompt` 表示约束不足或无法可靠验证。两者均提供 `code`。

### v2 状态接口

- `agent_sdk.state.StateStore`：内存中的会话／对局隔离状态；`apply_sync` 确认连续事件，`apply_decision` 接受同一时点完整快照、事件和提示，计算净差异。`get_state`、`get_zone`、`get_events` 为按版本读取接口，`get_status` 返回当前 `state_version` 与 `ack_event_id`。
- `agent_sdk.state_journal.StateJournal`：每次请求先在状态副本上校验和应用，再将含事件、快照与差异的完整检查点原子写入本地文件；成功后才确认事件。它不是追加日志实现。
- `agent_sdk.test_server`：确定性测试端支持 `POST /v2/decision`、`/v2/sync`、`/v2/status`，同时保留 v1 决策入口。`/v2/status` 用于客户端 F10 恢复 Agent 时核对服务端状态，不执行动作。测试端按实际卡库校验 SHA-256，不接受模型生成的原始协议字节。

v2 每次真实决策仍发送本方可见的完整快照；服务端据此替换状态并与上个版本比较。事件在收到持久确认前由客户端保留，未知关键消息和事件缺口使自动决策失败并交还人工。状态查询工具的 LLM 接线及追加日志方案属于二期服务工作。

Action 字段严格限制，拒绝原始 CTOS 参数及额外动作字段；请求/响应 envelope 允许新增可选字段。重复 JSON 键、非有限数、布尔值冒充整数、未知候选均拒绝。未知 constraints 语义拒绝，不能静默忽略。

## 组合约束约定

| 提示 kind | action.kind | 约束及候选字段 |
| --- | --- | --- |
| idle_command / battle_command / yes_no / effect_yes_no / option / chain / position / announce_number / rock_paper_scissors / first_player | choice | 当前候选 ID；可带 cancelable |
| unselect_card / select_unselect_card | select_step | 当前候选 ID；可带 cancelable |
| select_card / select_cards | select_cards | min_count/max_count 或 count；候选 mandatory:boolean |
| tribute | select_cards | 数量约束 + min_weight；可选 max_weight 为信息上界，不作为引擎拒绝条件；候选 weight:非负整数 |
| sum | select_cards | 数量约束 + mode:exact 或 at_least + target；候选 value_options:一至两个非负整数、mandatory:boolean |
| sort | select_cards | 所有 kind=card 候选的完整排列，排除 default 控制项，数组顺序即排序结果 |
| announce_race / announce_attribute | select_cards | 数量约束；候选 bit:唯一的二次幂 |
| place / select_place / disfield | select_places | count 或 min_count/max_count；每个候选直接包含 controller/location/sequence |
| counter / select_counter | distribute_counters | total_count；候选 max_count；allocations 含 candidate_id/count |
| announce_card | announce_card | allowed_card_ids：调用方已经可靠解析声明过滤条件的允许密码集合 |

`cancelable` 只声明 UI 状态，不自动允许空选或新增取消动作；合法取消/完成应由客户端明确提供候选。select_cards/tribute 的 cancel、sort 的 default 和 select_unselect_card 的 finish/cancel 支持 choice。组合选择不能包含这些控制候选。place.location 接受 mzone/szone 或 monster/spell，必须与当前候选完全一致。

SUM exact 校验是否存在一组候选值使总和恰好为 target。at_least 与引擎一致：全部所选素材（含 mandatory）的 max_sum >= target 且 min_sum - min(all_material_min) < target。exact 动态规划超过 1000000 次转移时返回 UnsupportedPrompt。SUM 的 candidate_ids 包含 mandatory，min_count/max_count 也含 mandatory 数量。没有可靠的 value_options/权重/声明允许集合时拒绝验证。

## 开发验证

```sh
cd agent_sdk
uv sync
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv run --extra scenario python -m unittest discover -s tests -v
```
