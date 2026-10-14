# 决斗策略指南编写 Skill 验证

> 状态：现行验证记录；截至 2026-10-14。仅覆盖开发期模板与确定性检查；操作入口见[编写流程](../guides/duel-knowledge-authoring.md)。

在 macOS 本地使用 Python 3.12，以 `deck/test/test.ydk` 生成本方填写稿，并以两个已有卡片 ID 生成热门系列填写稿；两份输出均写到 `/tmp`，未加入正式策略目录。原始空白填写稿执行 `guide.py check` 均返回未填写栏目与单卡用法。将必填元信息改为合法日期和 `OCG`，把其余空白标为带原因的待验证内容后，两种模式的结构与卡片清单检查通过。此构造填写稿只验证辅助脚本，不构成可收录的策略指南。

另将本方卡表中的一张卡由 3 张改为 2 张、在热门卡表中加入多余列；两份篡改稿均被拒绝，分别报告 `.ydk` 数量不一致和表格列数不符。

同时执行 `python3 tools/check-docs.py`、`ruff check`、`ruff format --check`；Skill Creator 的 `quick_validate.py` 返回 `Skill is valid!`。`docs/draft/` 已从索引检查和 Git 中排除。

尚未验证真实用户打法的多轮追问、指南策略质量、人工审核与正式收录；运行时装载及 BO3 换备牌不属于本次验证。
