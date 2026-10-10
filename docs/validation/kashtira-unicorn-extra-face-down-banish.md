# 俱舍怒威族·独角兽③：额外卡组里侧除外验证

> 状态：现行验证记录；截至 2026-10-11 的 macOS 开发环境实测。场景已收入[正式回归集](../../tests/scenarios/kashtira-unicorn-extra-face-down-banish/README.md)；格式见[严格场景契约](../contracts/agent-scenario-v1.md)。

人工双客户端录制 `8b8d37bcddbd4c7ea654c8c041ea31d4` 中，双方均收到权威终局，Guest 获胜。启动器初次编译失败，原始 `manifest.json` 保留 `compile_failed`：编译器误要求 Host 里侧除外卡的序号也出现在 Guest 的对手除外区卡片列表。实际 Host 可见该卡的序号和身份，Guest 的当前快照只有对手除外区数量及隐藏数量。修正交叉核对后，对同一双端日志离线重编译为 `compiled`，无错误或阻断项；本次修正没有改变游戏服务端或客户端消息。

录制中 Host 发动「日光独角兽」怪兽效果后，Guest 接受「俱舍怒威族·独角兽」③的发动提示。Guest 收到 `cards_revealed`，知晓对手额外卡组唯一的「闪电三角兽」（49389523）及序号 0；随后的 `select_cards` 从该序号选择一张。双端事件均显示从 Host 额外卡组到除外区的移动。Host 后续快照记录自己的「闪电三角兽」里侧除外；Guest 后续快照只见对手除外区增加一张隐藏卡。入库 YAML 将双方的展示、移动路径、连锁事件和后置可见状态分别写入断言。

验证结果：

- 重编译报告：`out/duel-recordings/8b8d37bcddbd4c7ea654c8c041ea31d4/draft/compile-report.json`，`compiled`，Host 5 步、Guest 6 步。
- 原始草稿 HTTP v3 双客户端无头回放 `passed`：`out/agent-e2e-runs/1791654373-1808/scenario-report.json`。
- 补齐目标断言的候选回放 `passed`：`out/agent-e2e-runs/1791654672-8490/scenario-report.json`。
- 收录后运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir --timeout 180`，当前八场景全部通过、零失败、零不支持；汇总报告 `out/agent-e2e-runs/batch-1791654878-13235/batch-report.json`，本场为第 3 项。
- 编译器单元测试 14 项、场景单元测试 31 项通过；Ruff 检查与格式检查通过。

目标中的发动、确认、选择与里侧除外已在协议和回放层验证。本局对手额外卡组只有一个候选，不能证明多候选选择。真实模型、GUI 剧本播放及 Windows 未验证。用户已审核目标解释和断言范围，场景收入 `tests/scenarios/kashtira-unicorn-extra-face-down-banish/`。
