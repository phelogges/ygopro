# 宣言卡名与选项文字验证

> 状态：历史验证记录，截至 2026-10-11；场景已由用户确认收录至 [tests/scenarios/lullaby-of-obedience-announce-card](../../tests/scenarios/lullaby-of-obedience-announce-card/README.md)。现行协议见 [HTTP v3](../contracts/agent-http-v3.md)与[动作契约](../contracts/duel-actions.md)。

人工双端录制 `e1761159a46445e381cccffdaa6f2e0b` 使用不洗牌的单局 1v1。Host、Guest 各发动一次「天声的服从」：前者宣言「地狱亡灵」并经对手选择特殊召唤，后者宣言「骨鼠」并经对手选择加入手牌。录制清单与自动回放均为 `validated`；编译报告 `compiled`、双端各 7 步，无阻断。原始双端日志保存在本机忽略目录 `out/duel-recordings/e1761159a46445e381cccffdaa6f2e0b/`。

录制提示各包含 7,125 个 `allowed_card_ids`，单个 `prompt` JSON 约 70,592 字节；两次选项候选原先只带通用“选择选项”。客户端补充 `DataManager::GetDesc` 的同源文本解析后，单场 HTTP v3 回放中的两个 `option` 提示均分别带 `description: "加入手卡"`、`description: "特殊召唤"`，原始 `description_id` 与顺序不变。候选脚本同时检查双端效果、LP 支付、卡片展示、特殊召唤、卡组到手牌移动和终局；修复后的单场报告 `out/agent-e2e-runs/1791714350-43794/scenario-report.json` 为 `passed`、`duel_finished`，Host 胜，双端步骤剩余 0。未运行其他场景或批量回归。

用户确认收录后，本场景单独回放报告 `out/agent-e2e-runs/1791715314-65134/scenario-report.json` 为 HTTP v3 `passed`、`duel_finished`，Host 胜，Host/Guest 各剩余 0 步，无忽略决策。本次只运行此剧本，未重跑其他场景或批量回归。

宣言提示的完整合法 ID 集仍随 HTTP v3 决策请求进入服务端，供 SDK 和客户端校验；两个模型入口改为只显示集合数量，避免向模型上下文复制该列表。macOS Debug 客户端编译及 `agent_codec` CTest 通过；Pydantic AI 与 Codex 的离线模型测试验证模型输入不含完整 ID、返回的 ID 仍通过原始约束校验。随后把描述搜索工具更名为 `search_card_descriptions`，另增 `search_card_names`；本地卡库离线验证卡名命中、同名多 ID、分页及字面 `%` 搜索，Pydantic AI CodeMode 和 Codex MCP 各走一次新工具。`agent_server` 相关测试 28 项、MCP socket 测试 3 项、技能测试 2 项通过；Ruff 和 Pyright 通过。尚未通过真实模型验证其选择质量、延迟、GUI Agent 接管与 Windows。
