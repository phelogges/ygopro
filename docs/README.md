# Agent 文档总索引

> 状态：现行文档入口；截至 2026-10-11。每页标题后的状态说明其适用范围。现行契约定义行为，设计解释取舍，指南提供操作步骤，验证记录只证明当时实际执行的路径。

当前正式客户端与 Agent 服务使用 **HTTP v3**。`tools/agent-e2e.py` 的三局回归和 YAML 场景回放默认也使用 **HTTP v3**：每个客户端启动独立的离线 Agent 服务，场景模式另由共享脚本协调器提供动作。`--protocol v2` 仅用于历史兼容回归；场景 YAML 自身的 v1/v2 版本与 HTTP 版本独立。旧版协议和阶段设计保留用于兼容测试及理解演进，不能直接套到正式服务。

## 现行契约

| 范围 | 文档 |
| --- | --- |
| 客户端与正式服务 | [HTTP v3](contracts/agent-http-v3.md) · [动作映射](contracts/duel-actions.md) |
| Agent 共用能力 | [工具语义](contracts/agent-tools-v1.md) · [人类只读可观测性](contracts/agent-observability-v1.md) |
| 对局录制与回归 | [双端录制](contracts/duel-recording-v1.md) · [确定性场景 YAML v1](contracts/agent-scenario-v1.md) · [随机结果场景 YAML v2](contracts/agent-scenario-v2.md) |
| 历史兼容测试端 | [HTTP v2](contracts/agent-http-v2.md)，显式指定 `--protocol v2` |

## 现行设计

| 范围 | 文档 |
| --- | --- |
| 服务与状态 | [二期服务总设计](design/agent-phase-2.md) · [现行状态数据流](design/agent-state.md) · [Codex 后端](design/agent-codex-backend.md) |
| 人类观察 | [可观测性设计](design/agent-observability.md) |
| 录制和回归 | [人工双端录制](design/manual-duel-capture.md) · [场景制作](design/duel-scenario-authoring.md) · [GUI 回放](design/agent-gui-e2e.md) |
| 消息完整性 | [客户端游戏消息覆盖审计](design/agent-message-coverage.md) |

## 操作指南

| 任务 | 文档 |
| --- | --- |
| 人工对局与录制 | [启动 Agent 对局](guides/agent-live-duel.md) · [双端录制](guides/manual-duel-capture.md) |
| 场景测试 | [制作场景](guides/duel-scenario-authoring.md) · [运行无头或 GUI 回放](guides/scenario-replay.md) |
| 后端与发版 | [Codex 初始化](guides/codex-backend.md) · [macOS 发行](guides/agent-release.md) |

## 验证与待办

[验证总览](validation/README.md)按路径、平台与后端列出仓库内最近一次实际证据及未验证项；[默认 v3 场景回放记录](validation/agent-v3-scenario-replay.md)区分当前入库场景与已移除剧本的历史报告，[场景清单](../tests/scenarios/README.md)列现行各局的目标和报告。[现行待办](roadmap.md)只列尚未完成或尚待实测的工作。

以下各页保留带日期或阶段范围的原始证据，旧测试数量与“当时未实现”的表述不代表今天的状态：

- [一期状态](validation/phase-1-status.md) · [二期服务](validation/agent-phase-2.md) · [v3 场景回归](validation/agent-v3-scenario-replay.md) · [旧回归入口](validation/agent-e2e.md) · [GUI 真实对局入口](validation/agent-live-duel.md)
- [人工录制](validation/manual-duel-capture.md) · [场景制作](validation/duel-scenario-authoring.md) · [随机结果消息](validation/agent-random-results.md) · [区域笔记](validation/agent-zone-notes.md)
- [魔术礼帽盖卡洗切](validation/magical-hats-set-shuffle.md)：2026-10-10 的随机场景候选与双端回放证据。
- [游戏消息覆盖审计](validation/agent-message-coverage.md)：2026-10-10 的静态分类、注入测试与 CTest 证据。
- [当前单局消息解析](validation/agent-message-coverage-2026-10-11.md)：2026-10-11 的 14 类消息解析与回归证据。
- [雷火沸动交界机③非连锁无效](validation/raikasen-nonchain-negation.md)：2026-10-11 的双端录制、区间计数断言与候选回放证据。
- [天子的指轮②自动无效](validation/angel-ring-mandatory-spell-negation.md)：2026-10-11 的双端录制、效果无效与非连锁断言证据。
- [连续速攻魔法卡连锁](validation/quick-play-ten-link-chain.md)：2026-10-11 的十项连锁双端录制、候选回放及入库证据。
- [俱舍怒威族·独角兽③额外卡组里侧除外](validation/kashtira-unicorn-extra-face-down-banish.md)：2026-10-11 的双端录制、可见性校验修正及入库回放证据。
- [魔导战士 破坏者③破坏魔陷卡](validation/breaker-spell-trap-destroy.md)：2026-10-11 的指示物序列化修复、双端破坏事件及入库场景回放证据。
- [河马狂欢节①三只衍生物](validation/hippo-carnival-three-tokens.md)：2026-10-11 的双端特殊召唤事件、区间计数断言及入库场景回放证据。
- [黑羽-热风之基布利②交换攻守](validation/blackwing-gibli-stat-swap.md)：2026-10-11 的双端数值变化、回合结束恢复及候选回放证据。
- [心变①取得控制权](validation/change-of-heart-control.md)：2026-10-11 的双端跨控制者移动、结束阶段归还及候选回放证据。
- [妖精传姬-辉夜②返回手牌](validation/fairy-tail-luna-bounce.md)：2026-10-11 的成功弹回与送同名卡无效分支双端证据。
- [天岩户②结束阶段回手](validation/amanowato-end-phase-return.md)：2026-10-11 的强制发动、回手及隐藏手牌双视角入库验证。
- [炎王妃 火神不死鸟①检索怪兽](validation/fire-king-consort-search.md)：2026-10-11 的破坏、检索、公开展示与等级变化入库验证。
- [哥布林德伯格①手牌特殊召唤](validation/goblinbergh-hand-special-summon.md)：2026-10-11 的双方各一次特殊召唤与表示形式变化入库验证。
- [长枪龙①穿透伤害](validation/spear-dragon-piercing-damage.md)：2026-10-11 的双端战斗数值、1400 点伤害与表示形式变化入库验证。
- [神机王 乌尔①逐只攻击与②伤害归零](validation/machine-king-ur-all-monsters-zero-damage.md)：2026-10-11 的双端两次攻击、零伤害区间断言与入库单场回放证据。
- [人偶兵卒①直接攻击](validation/doll-soldier-direct-attack.md)：2026-10-11 的对手有怪兽时直接攻击、800 点伤害与入库单场回放证据。
- [DNA 移植手术改变表侧怪兽属性](validation/dna-transplant-attribute-change.md)：2026-10-11 的双阶段属性变化、通用数值事件及入库单场回放证据。
- [DNA 改造手术改变表侧怪兽种族](validation/dna-surgery-race-change.md)：2026-10-11 的双阶段种族变化、通用数值事件及入库单场回放证据。
- [天声的服从宣言卡名与选项文字](validation/announce-card-options-2026-10-11.md)：2026-10-11 的双端录制、候选单场回放、选项文字修复与模型输入精简证据。
- [后端配置选择](validation/agent-backend-config-2026-10-11.md)：2026-10-11 的双后端配置段、启动器、发布检查与离线回放验证。
- [Agent 镜像与旧版笔记工具](validation/agent-mirror-tools-2026-10-11.md)：2026-10-11 的 Pydantic AI 与 Codex MCP 工具清单、历史笔记只读视图及协议兼容回归证据。
- [Codex 后端](validation/agent-codex-backend.md) · [可观测耗时](validation/agent-observability-timing.md) · [终局取消](validation/agent-terminal-cancellation.md) · [发行验证](validation/agent-release.md)

## 历史设计与兼容入口

- [HTTP v1](contracts/agent-http-v1.md)：一期原始请求；正式服务与默认确定性测试均使用 v3。
- [旧版认知笔记](contracts/agent-knowledge-notes-v1.md) · [旧手牌笔记路径](contracts/agent-hand-note-v1.md)：历史工具契约与迁移页；当前 Agent 通过事件历史重建判断。
- [一期设计](design/agent-phase-1.md) · [v2 状态设计](design/agent-state-v2.md) · [duel-001 制作记录](design/duel-001-e2e.md)：保留阶段背景和原始取舍。

更新接口或工具时，先改对应现行契约和测试，再核对设计、指南与验证证据。若代码和契约出现新的行为差异，先列出差异与影响，与用户讨论处理方式。文档相对链接、索引覆盖和状态标记可从仓库根运行 `python3 tools/check-docs.py` 检查；语义一致性仍需人工对照代码。
