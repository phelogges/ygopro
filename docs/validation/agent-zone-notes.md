# 对手隐藏区域认知笔记验证

> 状态：历史验证记录；截至 2026-10-10。覆盖魔陷区、场地区与主怪兽区录制和离线笔记工具；现行验证范围见[验证总览](README.md)。

2026-10-09 基于人工双客户端录制 `6aba04db61ae42fc8301a5165b60bb75`，确认 Guest 本视角的 `card_set` 事件和后续 `cards_revealed` 事件都包含魔陷区 `location=8, sequence=3`；后者包含 `card_id=89023486`。Guest 当前快照仍把该盖卡标为 `known=false`。先前“展示事件缺少序号”的判断经对实际 Agent 服务报告复核后更正。

经用户审核的剧本位于 `tests/scenarios/snake-eye-deck-set/`。其 `event_assertions` 分别检查双方的盖放和展示事件，包括卡片 ID 与公开格子序号；Guest 后置快照检查序号 3 有一张里侧盖卡，不要求权威快照暴露身份。正式路径回放报告 `out/agent-e2e-runs/1791560888-2716/scenario-report.json` 为 `passed`、`duel_finished`，Guest 获胜，双方步骤耗尽。

服务端新增 `zone="spell"` 的对手魔陷区推断笔记，与原有 `zone="hand"` 分开持久保存并按单方视角隔离。模型每轮输入包含两区当前说明；Pydantic AI 与 Codex MCP 共用读写接口，记录真实事件 ID 和修订历史。只读网页可分别查看两区说明。程序不把笔记内容写回权威快照，也不自动判定卡片离位后的推断是否仍有效。

验证命令与结果：

```sh
cd agent_server && .venv/bin/python -m pytest tests -q  # 59 passed
cd agent_server && .venv/bin/ruff check src tests
cd agent_server && .venv/bin/pyright
cd agent_sdk && .venv/bin/python -m unittest discover -s tests -p test_scenario.py -v  # 23 passed
node --check agent_server/web/app.js
agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/snake-eye-deck-set/scenario.yaml --timeout 120
```

真实模型主动调用 `write_zone_note(zone="spell")` 和 Windows 运行尚未实测；离线模型工具测试、Codex MCP 路由测试及双客户端事件回放已分别验证其边界。

## 场地区从卡组盖放的录制

经用户审核的场景 `tests/scenarios/tenpai-field-set/` 来自人工双客户端录制 `5da8960aff234c089e3d576bfde4cf7e`。Guest 本视角的 `card_set` 与后续 `cards_revealed` 都给出 `spell` 大区序号 5；展示事件含 `card_id=30336082`，而当前场面仍把序号 5 的盖卡标为未知。正式路径报告 `out/agent-e2e-runs/1791563079-41425/scenario-report.json` 为 `passed`、`duel_finished`，Host 获胜。

客户端以 `spell` 区序号 5 表示场地区。现有 `zone="spell"` 的读写笔记可记录这项历史展示推断；场景同形事件的独立存储测试验证了读写路径。独立 `zone="field"` 笔记尚未实现，真实模型主动记录与修订及 Windows 回放未验证。细节和目标审核见[场景 README](../../tests/scenarios/tenpai-field-set/README.md)。

## 主怪兽区自身变为里侧表示的录制

录制 `62e7b8fbe66b4bccab6db404a9b3c117` 的实际操作方是 Guest。Host 在死亡骆驼表侧攻击表示时的快照 #104 已看到 `card_id=2326738`、怪兽区序号 0；随后收到 `effect_activated`（公开卡片 ID）与 `position_changed`（`location=4, sequence=0, face_up_attack -> face_down_defense`）。Host 的快照 #170 同一格变为 `known=false`，Guest 的己方快照仍为 `known=true`。候选包 `out/scenario-authoring/death-camel-self-set/` 增加两端事件与可见状态断言；独立回放 `out/agent-e2e-runs/1791563790-54129/scenario-report.json` 为 `passed`，Guest 获胜，双方步骤耗尽。

该证据足以让 Agent 将“序号 0 的里侧怪兽曾是死亡骆驼”作为有时间边界的推断记录；`position_changed` 本身没有卡片 ID，须结合先前本视角的公开身份。新版客户端仅对场上怪兽的 `effect_activated` 附上报文可见的格子序号，双端回放 `out/agent-e2e-runs/1791596789-4818/scenario-report.json` 为 `passed`，双方效果发动与表示变化断言均定位到序号 0。服务端已增加 `zone="main_monster", sequence=0..4` 的逐格笔记，离线测试覆盖存储、Pydantic AI、Codex MCP 和查看接口。位置复用或离位后的模型主动修订仍需实战验证；该回放未调用真实模型。

本次实现后，macOS 客户端构建、CTest 2 项、Agent 服务端测试 61 项、场景编译器测试 24 项均通过；Ruff、Pyright、网页脚本语法检查和 `git diff --check` 通过。Windows 构建、网页实际显示及真实模型主动写笔记尚未验证。

用户审核后，死亡骆驼场景已收入 `tests/scenarios/death-camel-self-set/`；从正式路径回放的报告 `out/agent-e2e-runs/1791600385-66953/scenario-report.json` 为 `passed`、`duel_finished`，Guest 获胜，双方步骤耗尽。
