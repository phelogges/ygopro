# 决斗策略指南编写流程

> 状态：现行开发期操作指南；适用于本方 `.ydk` 构筑指南和热门系列应对指南的草稿制作。运行时 Agent 不使用编写 Skill；当前服务尚不装载生成的策略指南。

先读[通用策略大纲](duel-strategy-outline.md)，再使用 [`duel-knowledge-authoring` Skill](../../.agents/skills/duel-knowledge-authoring/SKILL.md)。用户提供打法与判断，Skill 负责模板、客观事实核对、针对模糊或矛盾处追问，以及组织可审核的指南。热门系列的收录卡由用户决定；Skill 不验证热门程度或系列成员是否穷尽。

## 生成填写稿

从仓库根执行以下命令。脚本只用 Python 标准库和本地 `cards.cdb`；不查询禁限表，也不联网。
将示例中的系列名称和 ID 换成实际值，ID 必须存在于本地卡库。

```sh
python3.12 .agents/skills/duel-knowledge-authoring/scripts/guide.py new-own --ydk deck/test/test.ydk
python3.12 .agents/skills/duel-knowledge-authoring/scripts/guide.py new-popular --series 系列名称 --ids 12345678 23456789
```

填写稿分别生成在 `docs/draft/deck-guides/<相对 deck 路径展平名>/input.md` 和 `docs/draft/popular-series/<系列名>/input.md`。若路径已存在，脚本拒绝覆盖。模板保留 TCG/OCG、禁限卡表生效日期、复核日期、BO3 与备牌栏目。本方卡表按 `.ydk` 的主卡、额外、备牌预填 ID 与张数；热门单卡表按用户给定的 ID 预填。卡片效果和数值由 Skill 查询本地卡库核实，用户主要填写单卡基本用法和整体策略。

## 审查与收录

用户填好 `input.md` 后，把路径交给 Skill。可先运行：

```sh
python3.12 .agents/skills/duel-knowledge-authoring/scripts/guide.py check docs/draft/deck-guides/test_test/input.md
```

`check` 检查模板类型、必填栏目、环境与日期、ID、重复项、卡库存在性和本方 `.ydk` 数量一致性；它会报告尚未填写的栏目，不评判策略好坏或禁限合法性。Skill 再核查具体卡片与规则事实，使用 `$grilling` 多轮质疑关键判断。用户的原始填写稿保留不改，生成稿与问题清单另存同一草稿目录。尚未证实的推断应标明“待验证”与失效条件；影响主要行动且没有依据的结论不作为确定建议。

用户审核生成稿与原稿差异后，正式指南分别收录到 `.agents/prompts/deck-guides/<构筑名>/readme.md` 和 `.agents/prompts/popular-series/<系列名>/readme.md`；长篇分支可拆到同目录专题文件，由入口链接。审核前不写正式目录。已有指南更新同样先产出修订草稿和变更摘要，再经人工审核替换；旧版由 Git 历史保留。

`docs/draft/` 被 Git 忽略，且被文档索引检查跳过；正式指南目前也不会自动进入模型上下文。运行时装载、禁限资料引用与 BO3 换备牌执行需要另外设计和验证。先攻、后攻、受阻后路线及新证据推翻原判断的样稿试运行，须在用户提供具体打法后进行。
