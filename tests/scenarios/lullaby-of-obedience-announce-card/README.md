# 「天声的服从」宣言卡名与两种结算分支

> 状态：已由用户确认收录的严格回归场景。目标原话与整理见 [goal.md](goal.md)，执行脚本见 [scenario.yaml](scenario.yaml)。

## 录制与对局

- 人工双客户端录制 ID：`e1761159a46445e381cccffdaa6f2e0b`。不洗牌单局 1v1，双方卡组由录制提交的 YDK 固定。清单和自动回放均为 `validated`；编译 `compiled`，Host 和 Guest 各 7 个决策步骤，无阻断。
- Host 第 1 回合发动「天声的服从」（39238953），支付 2000 LP，宣言「地狱亡灵」（40575313）。Guest 检查自己卡组，选出一张并选择特殊召唤分支；Host 再为该怪兽选自己的怪兽区 1，特殊召唤完成。
- Guest 第 2 回合发动同名魔法，支付 2000 LP，宣言「骨鼠」（21239280）。Host 从自己卡组的三张同名卡中选第 2 张，选择加入手牌分支；Guest 手牌增加公开确认过的「骨鼠」。Guest 最后投降仅用于进入权威终局，Host 获胜。

## 目标审核

1. **已验证，语义动作与回放**：双端各有 `announce_card` 提示和 `announce_card(card_id)` 响应，分别为 40575313 和 21239280。HTTP v3 单场回放复现两次动作及后续结算，不依赖模拟键盘输入或列表点击。选中卡片 ID 属于提示时客户端解析出的合法集合，并由 SDK 与客户端分别校验。
2. **已验证，特殊召唤分支**：Guest 的后续提示为 `select_cards`、`option`，选出的「地狱亡灵」被双方看到；随后 Host 收到 `select_place` 并把它特殊召唤到自己的怪兽区 1。场景在 Host/Guest 两端检查公开展示、特殊召唤事件、后置怪兽区和双方 LP。
3. **已验证，加入手牌分支**：Host 从卡组选择「骨鼠」并在 `option` 选择加入手牌，Guest 的已接受事件包含该卡从对手卡组移至自己手牌及再次展示；双端后置快照只按各自视角检查手牌数量与已知身份。
4. **未验证，真实模型决策质量**：本场使用离线脚本决策。未运行 Pydantic AI/Codex 真实模型，不能以回放通过证明模型会正确理解卡名、猜测对手卡组内容或解释二选一候选。

## 发现的 Agent 接入限制

- 原始 `MSG_ANNOUNCE_CARD` 合法集合在这局有 7,125 个卡片 ID，每端提示的 `prompt` JSON 约 70,592 字节。后续修复使 Pydantic AI 和 Codex 的模型输入只显示集合数量，完整列表留在 SDK 与客户端校验中；客户端到服务端的传输和持久存储目前仍保留完整列表。
- 原始录制中 `option` 的候选 `description` 都是“选择选项”，只有不同的 `description_id`。后续修复令客户端像 GUI 一样从本地卡库解析文字；`627823248` 为“加入手卡”，`627823249` 为“特殊召唤”。修复后的本场回放已核对两端决策请求中的具体文字。
- 后续已把描述搜索工具明确为 `search_card_descriptions`，并新增 `search_card_names`，可按卡名查 ID。真实模型能否选对目标尚待对局验证；候选 ID 仍由服务端和客户端按本次提示校验。

## 验证证据与边界

- 原始双端日志、编译报告和时间线：`out/duel-recordings/e1761159a46445e381cccffdaa6f2e0b/`。录制自动回放报告：`out/agent-e2e-runs/1791712980-13696/scenario-report.json`。
- 补充双端有序事件断言后的候选单场 HTTP v3 回放报告：`out/agent-e2e-runs/1791713333-21398/scenario-report.json`，`passed`、`duel_finished`，Host 胜，双端步骤耗尽。未运行其他场景或批量回归。
- 选项文字与模型输入精简修复后，候选单场回放报告 `out/agent-e2e-runs/1791714350-43794/scenario-report.json` 也为 `passed`、`duel_finished`；双端决策请求均有“加入手卡”“特殊召唤”文字。确定性后端测试证明模型输入不包含完整合法 ID 列表，但真实模型未执行。
- 用户确认收录后，仅回放本场景：`out/agent-e2e-runs/1791715314-65134/scenario-report.json` 为 HTTP v3 `passed`、`duel_finished`，Host 胜；Host/Guest 各剩余 0 步，无忽略决策。未运行其他剧本或批量回归。
- 本场没有覆盖宣言对手卡组中不存在的卡、别名或同名卡边界、未确认卡片时的回退、真实模型输入大小与超时、GUI Agent 接管、Windows。
