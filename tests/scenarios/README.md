# 双客户端场景回归集

每个场景目录保存 `scenario.yaml`、本场景固定的 `host.ydk` 与 `guest.ydk`、`goal.md` 和 `README.md`。`goal.md` 分开保留用户原话与 Agent 整理的可核查目标；历史原话缺失时标记事后重建。README 说明证据、验证状态和限制。原始双端日志、密钥及诊断报告留在 Git 忽略的 `out/`，不入库。

本回归集验证客户端在 Agent 决策前提供的合法候选、本方可见快照与事件，以及语义动作回译后能否完成预期对局。场景的机器通过结果只证明写入的断言成立；自然语言目标的充分性还需人工审核。制作步骤见[场景指南](../../docs/guides/duel-scenario-authoring.md)，流程取舍见[设计](../../docs/design/duel-scenario-authoring.md)，格式见[严格场景 v1](../../docs/contracts/agent-scenario-v1.md)与[随机场景 v2](../../docs/contracts/agent-scenario-v2.md)。新场景使用简短功能名。

场景 YAML 版本与 Agent HTTP 版本独立。当前 `tools/agent-e2e.py --scenario` 默认使用 HTTP v3；历史 HTTP v2 回归须显式指定 `--protocol v2`。本目录现收录 22 个经人工双客户端录制、Agent 审核并由用户确认的场景；原有其他剧本已从回归集移除。历史八场景回放记录只作为当时的验证证据，不能代表当前场景清单；当前证据见[验证记录](../../docs/validation/agent-v3-scenario-replay.md)、[魔术礼帽随机场景记录](../../docs/validation/magical-hats-set-shuffle.md)、[雷火沸动交界机非连锁无效记录](../../docs/validation/raikasen-nonchain-negation.md)、[天子的指轮自动无效记录](../../docs/validation/angel-ring-mandatory-spell-negation.md)、[连续速攻魔法卡连锁记录](../../docs/validation/quick-play-ten-link-chain.md)、[俱舍怒威族·独角兽③记录](../../docs/validation/kashtira-unicorn-extra-face-down-banish.md)、[魔导战士 破坏者③记录](../../docs/validation/breaker-spell-trap-destroy.md)、[河马狂欢节①记录](../../docs/validation/hippo-carnival-three-tokens.md)、[黑羽-热风之基布利②记录](../../docs/validation/blackwing-gibli-stat-swap.md)、[心变①记录](../../docs/validation/change-of-heart-control.md)、[妖精传姬-辉夜②记录](../../docs/validation/fairy-tail-luna-bounce.md)、[天岩户②记录](../../docs/validation/amanowato-end-phase-return.md)、[炎王妃①记录](../../docs/validation/fire-king-consort-search.md)、[哥布林德伯格①记录](../../docs/validation/goblinbergh-hand-special-summon.md)、[长枪龙①记录](../../docs/validation/spear-dragon-piercing-damage.md)、[神机王 乌尔①②记录](../../docs/validation/machine-king-ur-all-monsters-zero-damage.md)、[人偶兵卒①记录](../../docs/validation/doll-soldier-direct-attack.md)、[DNA 移植手术属性变化记录](../../docs/validation/dna-transplant-attribute-change.md)及[DNA 改造手术种族变化记录](../../docs/validation/dna-surgery-race-change.md)。

批量回放当前目录下全部场景，运行 `uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario-dir`。每个场景包必须有 `scenario.yaml`、`host.ydk`、`guest.ydk`、`goal.md`、`README.md`，缺少文件会在汇总中失败；文本目标和断言的充分性仍须按[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)人工审核。批量入口对随机场景调用采样工具，逐局结果和失败日志汇总到本次运行的 `batch-report.json`。具体参数见[回放指南](../../docs/guides/scenario-replay.md)。

| 场景 | 类型 | 主要覆盖 | 本轮验证 | 尚未证明 |
| --- | --- | --- | --- | --- |
| [snake-eye-deck-set](snake-eye-deck-set/README.md) | 严格 | 黑魔女从卡组盖放「原罪宝－蛇眼」、双方展示事件与盖卡可见性 | 2026-10-09 双端终局通过 | 真实模型写魔陷区笔记、Windows 回放 |
| [tenpai-field-set](tenpai-field-set/README.md) | 严格 | 天杯龙从卡组盖放「杯满的灿幻庄」到场地区、双方展示事件与盖卡可见性 | 2026-10-10 双端终局通过 | 真实模型写场地区推断、Windows 回放 |
| [death-camel-self-set](death-camel-self-set/README.md) | 严格 | 死亡骆驼自身变为里侧守备、双方公开事件及隐藏身份边界 | 2026-10-10 双端终局通过 | 真实模型写怪兽区推断、Windows 回放 |
| [magical-hats-set-shuffle](magical-hats-set-shuffle/README.md) | 随机 | 魔术礼帽从卡组盖放两张魔陷卡、展示与三卡洗切、战斗阶段结束清理 | 2026-10-10 双端 checkpoint 两次通过；同日四场景批量回归通过 | 隐藏排列全覆盖、真实模型、GUI 与 Windows 回放 |
| [quick-play-ten-link-chain](quick-play-ten-link-chain/README.md) | 严格 | 双方交替发动速攻魔法，形成同一条十项连锁并逆序处理 | 2026-10-11 双端终局、41 条有序事件断言与区间计数断言及七场景批量回归通过 | 真实模型、GUI 与 Windows 回放 |
| [kashtira-unicorn-extra-face-down-banish](kashtira-unicorn-extra-face-down-banish/README.md) | 严格 | 俱舍怒威族·独角兽③确认对手额外卡组，选择一只怪兽里侧除外；双方展示事件与隐藏状态边界 | 2026-10-11 双端终局、目标断言及八场景批量回归通过 | 多候选选取、真实模型、GUI 与 Windows 回放 |
| [breaker-spell-trap-destroy](breaker-spell-trap-destroy/README.md) | 严格 | 破坏者③移除魔力指示物，破坏指定魔陷卡；双端效果与移动原因断言 | 2026-10-11 双端终局与目标断言、九场景批量回放通过 | 真实模型、GUI 与 Windows 回放 |
| [hippo-carnival-three-tokens](hippo-carnival-three-tokens/README.md) | 严格 | 河马狂欢节①在同一连锁处理中依次特殊召唤三只衍生物；双端卡片身份、格子及准确次数断言 | 2026-10-11 双端终局与目标断言、十场景批量回放通过 | 解放、额外卡组特殊召唤与攻击对象限制；真实模型、GUI 与 Windows 回放 |
| [blackwing-gibli-stat-swap](blackwing-gibli-stat-swap/README.md) | 严格 | 黑羽-热风之基布利②交换原本及当前攻守，回合结束后恢复；双端连锁事件与后置数值断言 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十一场景批量回放 | 效果无效、重叠数值修正、真实模型、GUI 与 Windows 回放 |
| [change-of-heart-control](change-of-heart-control/README.md) | 严格 | 心变①选择对方怪兽，取得控制权并在结束阶段归还；双端移动事件与前后场面断言 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十二场景批量回放 | 目标不合法、效果无效、期间离场、真实模型、GUI 与 Windows 回放 |
| [fairy-tail-luna-bounce](fairy-tail-luna-bounce/README.md) | 严格 | 妖精传姬-辉夜②成功将双方怪兽回手；再次发动时对方送同名卡使效果失效且零回手 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十三场景批量回放 | 额外卡组目标、目标离场、真实模型、GUI 与 Windows 回放 |
| [amanowato-end-phase-return](amanowato-end-phase-return/README.md) | 严格 | 天岩户②在召唤回合结束阶段强制发动并返回持有者手牌；双端连锁事件与隐藏手牌断言 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十四场景批量回放 | 控制权改变后的原持有者、效果无效、真实模型、GUI 与 Windows 回放 |
| [fire-king-consort-search](fire-king-consort-search/README.md) | 严格 | 炎王妃①破坏手牌的火山鼠并检索炎王神兽；双端移动、公开展示、隐藏手牌与可选等级变化断言 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十五场景批量回放 | 其他检索目标、场上素材、效果无效、真实模型、GUI 与 Windows 回放 |
| [goblinbergh-hand-special-summon](goblinbergh-hand-special-summon/README.md) | 严格 | 哥布林德伯格①在双方回合各从手牌特殊召唤一只怪兽，并使自身变守备；双端召唤事件与次数断言 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十六场景批量回放 | 效果无效、召唤失败、其他等级怪兽、真实模型、GUI 与 Windows 回放 |
| [spear-dragon-piercing-damage](spear-dragon-piercing-damage/README.md) | 严格 | 长枪龙①攻击里侧守备怪兽，核对 1900 对 500、1400 点穿透伤害、LP 变化及攻击后转守备 | 2026-10-11 原始录制、候选独立回放与收录后本场景单独回放通过；未运行十七场景批量回放 | 伤害无效或修正、守备力更高目标、真实模型、GUI 与 Windows 回放 |
| [machine-king-ur-all-monsters-zero-damage](machine-king-ur-all-monsters-zero-damage/README.md) | 严格 | 神机王 乌尔①先后攻击两只不同怪兽；②首次 1600 对 500 战斗不造成对方 LP 伤害 | 2026-10-11 原始录制及候选独立回放通过；收录后仅回放本场景，未运行十八场景批量回放 | 三只以上目标、攻击重放、其他伤害修正、真实模型、GUI 与 Windows 回放 |
| [doll-soldier-direct-attack](doll-soldier-direct-attack/README.md) | 严格 | 人偶兵卒①在对手仍有怪兽时直接攻击玩家，造成 800 点战斗伤害；双端目标、伤害与 LP 断言 | 2026-10-11 原始录制及候选独立回放通过；收录后仅回放本场景，未运行十九场景批量回放 | 攻击无效、伤害修正、②效果、真实模型、GUI 与 Windows 回放 |
| [dna-transplant-attribute-change](dna-transplant-attribute-change/README.md) | 严格 | 两张 DNA 移植手术依次宣言神与风；双方表侧怪兽暗／炎→神→风，双端快照与通用数值事件断言 | 2026-10-11 候选及收录后单场回放通过；未运行二十场景批量回放 | 新怪兽入场、陷阱离场恢复、真实模型、GUI 与 Windows 回放 |
| [dna-surgery-race-change](dna-surgery-race-change/README.md) | 严格 | 两张 DNA 改造手术依次宣言幻想魔族与电子界族；双方表侧怪兽种族两阶段变化，双端快照与事件断言 | 2026-10-11 候选及收录后单场回放通过；未运行二十一场景批量回放 | 新怪兽入场、陷阱离场恢复、真实模型、GUI 与 Windows 回放 |
| [lullaby-of-obedience-announce-card](lullaby-of-obedience-announce-card/README.md) | 严格 | 双方各发动「天声的服从」并宣言卡名，分别完成特殊召唤与加入手牌分支；双端事件与后置快照断言 | 2026-10-11 候选及收录后本场景 HTTP v3 单场回放通过；未运行二十二场景批量回归 | 无卡命中、别名与同名卡边界、真实模型、GUI 与 Windows 回放 |
| [raikasen-field-nonchain-negation](raikasen-field-nonchain-negation/README.md) | 严格 | 雷火沸动交界机③在对方怪兽效果处理时取除素材、效果无效，且目标连锁只有一个连锁项 | 2026-10-11 双端终局回放、事件区间计数断言及六场景批量回归通过 | 真实模型、GUI 与 Windows 回放 |
| [angel-ring-mandatory-spell-negation](angel-ring-mandatory-spell-negation/README.md) | 严格 | 天子的指轮②自动无效旋风的魔法卡效果，不生成额外连锁项；被选装备卡留场 | 2026-10-11 双端终局、事件区间计数断言及六场景批量回归通过 | 每回合一次的次数上限、真实模型、GUI 与 Windows 回放 |

## 待覆盖的协议情况

- 已移除的基础召唤与有效连锁、长对局检索和多回合展开不再由当前入库场景专门覆盖；按[制作技能](../../.agents/skills/duel-scenario-authoring/SKILL.md)重新人工录制、审核并经用户确认后再补入。历史通过报告不能替代当前覆盖。
- 抛币、掷骰、随机选卡尚无入库场景，各自需要标准双端人工录制、可见事件断言及效果完成后的 checkpoint。不能用合成测试冒充真实对局覆盖。
- 结果改变后续玩家动作序列的随机效果仍需要条件分支能力；当前随机场景 v2 会明确拒绝将这类完整流程标为已验证。
- 其他复杂消息按实际录制暴露的缺口补充，分别检查 Host、Guest 的可见性，防止隐藏卡身份泄漏。

运行单个严格场景：

```sh
env PYTHONPATH=agent_sdk/src agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario tests/scenarios/snake-eye-deck-set/scenario.yaml
```

可单独使用 `tools/sample-random-scenario.py --scenario <场景路径>` 采样随机场景；批量入口也会调用它。单次失败立即失败，覆盖目标按场景声明的次数上限统计。
