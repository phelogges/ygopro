# 游戏王决斗策略理论资料调研

> 状态：现行调研记录，2026-10-14。本文保存外部来源、可迁移的观点和适用边界；[通用决斗策略大纲](../guides/duel-strategy-outline.md)是后续知识写作的顶层指南。本文不作为 Agent 运行时指令或当前环境的卡组推荐。

## 研究范围与结论

检索了英文、中文和日文的游戏王策略资料，重点关注获胜路径、资源与节奏、对局角色、展开韧性、阻抗时机、后攻路线、信息不确定性、局间备牌和复盘。资料并不存在一套公认且完整的统一决策算法；以下是多个作者的观点与我们的归纳。引用的 TCG、历史 OCG 及个别构筑案例只用来提炼分析方法，不能作为当前 OCG 禁限卡、具体卡片强度或构筑打法的结论。

| 议题 | 来源观点的归纳 | 可迁移的分析方法 |
| --- | --- | --- |
| 获胜路径 | 牌张和可循环资源、场面控制与节奏、直接达成胜利条件是不同的优势。[来源 1] | 同时看眼前场面、后续可用资源和能否终结；单纯数卡不足以评价局面。 |
| 对局角色 | 长局更有利的一方与必须尽快结束的一方，可能随起手、先后攻和实际场面互换角色。[来源 2] | 先判断当前应经营资源还是主动施压，再决定是否交换或冒险。 |
| 一致性与韧性 | 起动、补点和非引擎卡比例影响起手概率；概率不能单独说明遇到阻抗后的结果。[来源 3、4、6] | 把“能起动”和“被打断后仍有计划”分开评价。 |
| 阻抗时机 | 手坑可能在成场前降低对手收益；不同交点有不同的剩余补点和背面风险，未知手牌与构筑使时点选择带有不确定性。[来源 5、6、9] | 比较阻断后对手仍可做什么，不把一个时点写成绝对断点。 |
| 信息与复盘 | 行为可以提供线索，但推断不是已公开事实；复盘要追溯较早的可控选择。[来源 7、8] | 保留事实与假设的区别，分析当时可见信息下的替代路线。 |
| Match 与备牌 | OCG 店铺赛以先取两胜、最多三局决定 Match；第 2 局起可在局间交换备牌，第 1 局前不能交换。[来源 10] | 把局内决策与局间构筑决策分开，并保留前一局公开情报。 |
| 先后攻与交换 | 后续局由上一局败者选择先后攻，但局间交换发生在下一局开始流程之前；先攻方案和后攻方案的换入、换出侧重点不同。[来源 10、11] | 有选择权时先拟定方向；对方有选择权时为两种顺序保留可用性，不能把预测写成确定事实。 |
| 备牌容量 | 策略文章建议先确认主卡组里有多少可换出卡位，再选择有效的换入牌；换入过多可能破坏原构筑的起动与后续。[来源 11、12] | 每张换入牌都要有换出对应项和明确用途，整套交换后重新评估构筑。 |

“卡差”“终场阻抗数”只是分析视角：墓地或除外区可复用卡、下回合起动能力、位置、伤害威胁和未知手牌都会改变实际价值。这是对上述资料的综合推论，不是单一来源的规则。[来源 1、2]

## 备牌策略调研要点

**规则边界。** 截至检索日，Konami 的 OCG 店铺赛规程写明两胜制 Match、备牌 0—15 张、局间可与主卡组或额外卡组交换，交换前后主卡组与额外卡组的张数须分别保持不变，前一 Match 的换牌要在下一 Match 前复原。下一局的先后攻由上一局败者选择；比赛流程把局间备牌放在下一局开始之前。[来源 10] 具体活动可能有自己的规程，实际实施时以该房间或赛事规则为准。

**先确定局间目标，再确定交换。** Game 1 的公开行动有助于判断对手的资源路径、胜利方式与本方低效牌。局间要分别想：若预期先攻，哪些卡加强本方展开、保护终场或应对对方换入的解场；若预期后攻，哪些卡能在对手成场前干扰、成场后突破，或支持突破后的斩杀／返场。OCG 策略文章把先攻和后攻的换牌方向分开，并强调先找可换出的卡位。[来源 11] 对方也可能换牌，Game 1 观察到的构筑不能原样套到 Game 2/3；后一句是本文的推论。

**整体构筑仍要能运作。** 换入牌的强度不能只看它对对手是否有效，还要看所换出的起动、补点、检索目标与额外卡组配套是否让本方路线失效。应检查每个换入方案的实际可换出容量、先后攻适用性、抽到时的功能和与自身限制的冲突。资料中有“先确定换出卡”“提前练习换牌方案”和避免过度稀释引擎的建议；具体换牌数量没有通用常数。[来源 11、12、13]

**Game 3 重新判断。** Game 2 的公开信息、先后攻选择和双方可能已换入的牌，会改变 Game 3 的评估。不能机械地重复 Game 2 的换牌，也不应在复盘时利用对局中未公开的备牌身份。赛事时间与超时裁定依活动规程变化，当前研究只记录它是 Match 层的潜在条件，不把某一赛事的时间规则写成通用策略。[来源 10]

## 来源与可信边界

以下仅记录链接和研究用途，不复制原文。检索日期：2026-10-14。

1. Johnny Li，[There Are 3 Ways to Win at Yu-Gi-Oh!](https://www.tcgplayer.com/content/article/There-Are-3-Ways-to-Win-at-Yu-Gi-Oh/0cff6494-3b3b-4662-85bd-23eec17e2f5f/)，TCGplayer。资源、节奏和终结三种观察视角；具体历史卡例不适用于当前环境。
2. Johnny Li，[The Immortal Technique: The Most Powerful Skill in Yu-Gi-Oh](https://www.tcgplayer.com/content/article/The-Immortal-Technique-The-Most-Powerful-Skill-in-Yu-Gi-Oh/a713eb60-0509-48b9-abde-6086a7de7535/)，TCGplayer。对局角色、长期优势与局中角色切换；属于作者的策略观点。
3. TCGplayer，[YuGiOh Essential Theory 系列索引](https://www.tcgplayer.com/content/series/yugioh-essential-theory)。收录起动／补点、卡差、构筑和复盘专题；本次仅用来确认主题覆盖，不把索引标题当成详细论证。
4. Robin Schrecklinger，[The Mathematics Behind Building Competitive Decks](https://insight.cardmarket.com/en/Articles/The-Mathematics-Behind-Building-Competitive-Decks)，Cardmarket Insight。起动卡和手坑起手概率的超几何计算；概率不能单独衡量实战路线质量。
5. Ryan Atlus，[Going Second: Prevent a Board or Break It](https://insight.cardmarket.com/en/Articles/Going-Second-Prevent-a-Board-or-Break-It)，Cardmarket Insight。后攻时事前干扰与事后突破的不同方案；具体卡例与环境已过时。
6. Zuuucker，[游戏王 OCG 直播双子构筑浅谈：对局技巧与操作思路](https://www.bilibili.com/opus/939022603001004053)，2024。中文 OCG 个案，讨论资源牌型、试探阻抗、补点与妥协；不移植该构筑的具体路线。
7. Zachariah Butler，[Asking “Why” When You're Playing Yu-Gi-Oh!](https://www.tcgplayer.com/content/article/Asking-Why-When-You-re-Playing-Yu-Gi-Oh/09775325-8420-49b4-ab38-71a8f8133753/)，TCGplayer。规划动作和从行为推断信息；推断不等于已知事实。
8. Doug Zeeff，[5 Questions That Can Boost Your Win Rate in Yu-Gi-Oh](https://www.tcgplayer.com/content/article/5-Questions-That-Can-Boost-Your-Win-Rate/7d583635-3c0d-4fce-8def-4c0b5e33138b/)，TCGplayer。技术操作、构筑与环境判断的复盘顺序；赛事心理和体力部分不直接对应本项目 Agent。
9. まったり，[手札诱发的使用时点：仅持有灰流丽或无限泡影的情形](https://rinax-alba.com/archives/140)，2023 年 OCG 个人分析。先理解常见构筑的展开核心，再比较不同阻断点面临的未知手牌和未知构筑风险；示例数值随构筑变化，不能直接复用。
10. Konami，[遊戯王 OCG 店铺赛大会规程](https://www.yugioh-card.com/japan/event/regulation/duel/)，页面标注 2026-07-21。提供两胜制、备牌张数、局间交换、先后攻选择与每轮复原的官方边界；其他赛事可能另有规定。
11. たけっしー，[OCG 备牌构筑与局间交换基础](https://gachi-matome.com/p-yg-topic-20260829/)，ガチまとめ，2026-08-29。区分先攻和后攻换牌，建议先找可换出卡位；具体卡例和数量属于作者对当时环境的判断。
12. Kelly Locke，[Side Deck Theory: Planning For Going Second](https://www.tcgplayer.com/content/article/Side-Deck-Theory-Planning-For-Going-Second/13c558f8-8f35-4880-abf0-fe6135e83350/)，TCGplayer。后攻备牌规划；TCG 环境与时期的具体卡例不移植到 OCG。
13. TCGplayer，[How To Profit: 3 Ways To Make Bank At Regionals](https://www.tcgplayer.com/content/article/How-To-Profit-3-Ways-To-Make-Bank-At-Regionals/9d5f8992-4815-475c-b581-ca6c28a7c5da/)。其中关于赛前练习先后攻、不同对局的换牌模式可作为准备方法；赛事经验不是固定换牌公式。
