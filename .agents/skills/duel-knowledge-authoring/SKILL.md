---
name: duel-knowledge-authoring
description: 为本方 YDK 构筑或用户指定的热门系列制作决斗策略指南；生成填写模板，审查用户稿并多轮追问，产出待审核草稿。仅用于开发期知识编写，不用于运行时决斗。
---

# 决斗策略指南编写

本 Skill 只供开发 Agent 使用。先读[通用策略大纲](../../../docs/guides/duel-strategy-outline.md)和[编写流程](../../../docs/guides/duel-knowledge-authoring.md)。运行时 Agent 只显式加载规则书和卡库技能，不使用本 Skill；正式指南也尚未接入运行时。支持两种模式：绑定具体 `.ydk` 的**本方构筑运转指南**，以及由用户指定系列和热门单卡清单的**热门系列应对指南**。不要把热门清单的完整性或流行度当作可由卡库证明的事实。

## 生成填写模板

在仓库根使用 [`scripts/guide.py`](scripts/guide.py)：

```sh
python3.12 .agents/skills/duel-knowledge-authoring/scripts/guide.py new-own --ydk deck/test/test.ydk
python3.12 .agents/skills/duel-knowledge-authoring/scripts/guide.py new-popular --series 系列名称 --ids 12345678 23456789
```

模板源文件为 [`assets/own.md`](assets/own.md) 和 [`assets/popular.md`](assets/popular.md)。本方模式从实际 `.ydk` 预填主卡、额外、备牌 ID 与张数；热门模式只预填用户给出的卡。用户在单卡表填 ID 对应的基本用法，在其余栏目写整体思路、条件、限制及经验。两种模板均要求 TCG/OCG、禁限卡表生效日期及最后复核日期；不要求用户抄写卡片效果。临时文件默认在被 Git 忽略的 `docs/draft/`；脚本拒绝覆盖已有填写稿。

## 审查与追问

用户交回填写稿路径后，先运行 `guide.py check <input.md>`。脚本只检查格式、必填栏目、日期、卡片 ID、卡库存在性及本方 `.ydk` 的区域与张数；不判定策略好坏、系列热门程度或禁限合法性。保留原稿，不直接改写。再用 `$ygo-card-db` 核对涉及的卡片效果与名称，用 `$ocg-rulebook` 处理规则疑点；若环境时效或对局流行度需要外部资料，仅在用户要求或关键争议无法由已有材料判断时检索，并注明来源日期。没有独立禁限资料时把禁限合法性标为未核验，不自行推断。

**调用 `$grilling` Skill**，针对用户的输入分轮追问：对模糊路线、缺失的失败条件、阻抗后的残余资源、先后攻差异、对手可用补点、换备牌依据及与卡片事实冲突的说法提出具体问题。不要预设轮数；当前一轮的答案确定后再问依赖它的问题。区分用户策略、可核实事实、自己的推断和待验证假设；不能将推断润色成已证实打法。主要行动仍缺依据时，暂缓该部分的确定性建议。

## 生成与审核

在原稿同目录另写 `draft/` 中的 `readme.md`、必要的专题文件与 `questions.md`；本方长篇展开可拆为 `combo/`，热门系列长篇应对分支可拆为专题文件。入口应让读者先看到适用环境、禁限日期、决策要点、单卡表及细节链接。备牌章节保留：本方指南可写具体换入换出；热门指南只写应对目标、先后攻条件与对手可能调整，不假定本方固定牌表。本方的具体对局章节可留空。另写原稿到生成稿的差异摘要和仍待验证项。

向用户提交草稿、差异与问题，审核通过后才收录：本方到 `.agents/prompts/deck-guides/<相对 deck 路径展平名>/readme.md`，热门系列到 `.agents/prompts/popular-series/<用户指定目录名>/readme.md`。更新已有指南也先产出草稿和变更摘要。检查正式目录是否撞名；本方入口记录原始 `.ydk` 相对路径，热门入口记录显示名称。只有人工审核后的正式文件进入 Git；草稿不进文档索引和 Git。生成指南不代表运行时已装载，也不代表 BO3 备牌决策已实测。
