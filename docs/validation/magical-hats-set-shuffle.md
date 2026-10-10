# 魔术礼帽盖卡洗切录制与场景候选验证

> 状态：现行验证记录；截至 2026-10-10。记录 macOS 第三次录制 `fb98f0ad95ea4949968262d91584b89d` 的协议补全和候选回放；用户随后确认收录为[魔术礼帽场景](../../tests/scenarios/magical-hats-set-shuffle/README.md)。

## 录制与缺口

双端录制以 `MSG_WIN` 正常结束，房间启用“不洗牌”。「魔术礼帽」（81210420）效果将一只本方怪兽和从卡组选出的两张魔陷卡盖放为怪兽，双方收到 `MSG_CONFIRM_CARDS`（31）及 `MSG_SHUFFLE_SET_CARD`（36）。原客户端没有解析 36，后续 Agent 请求会被标记 `history_incomplete`；原随机场景编译器也未将 36 列为目标，因此不能据旧版草稿宣称协议通过。

现有修复将 36 转为只含本视角玩家、区域、数量的 `set_cards_shuffled` 事件，不发送盖卡身份与洗切映射。随机场景 v2 可声明 36 目标，编译器产出待审草稿。场景回放在目标报文后触发一次测试专用的后台同步，使没有后续决策的客户端也将已观察事件提交给 Agent 服务；正式决斗仍按原有决策与队列阈值同步策略运行。

## 实际执行

- macOS Debug：`cmake --build --preset MacOS-Debug` 通过；`ctest --test-dir out/build/MacOS-Debug -R agent_codec --output-on-failure` 的 2 项通过，包含消息 36 的合法与异常报文检查。
- `agent_sdk`：96 项 unittest 通过；本次修改涉及文件的 Ruff 检查通过。`python3 tools/check-docs.py` 通过。
- 双客户端无头 HTTP v3 回放候选 `out/duel-recordings/fb98f0ad95ea4949968262d91584b89d/candidate/scenario.yaml` 两次，均为 `checkpoint_passed`：`out/agent-e2e-runs/1791646471-56671/scenario-report.json`、`out/agent-e2e-runs/1791646518-57472/scenario-report.json`。第二次包含双方展示事件和中间三怪兽断言；两次原怪兽最后分别位于格子 3 与格子 0。
- 用户确认收录后，`tools/agent-e2e.py --scenario-dir --timeout 180` 的四场景批量报告 `out/agent-e2e-runs/batch-1791646840-63179/batch-report.json` 为 `passed: 4`、`failed: 0`；本场采样状态 `single_passed`、结果 `count:3`。

候选将原录制的随机格子攻击改为首个战斗指令直接进入主要阶段 2，故只验证不依赖洗切排列的效果前缀与战斗阶段结束状态。双端事件确认两张卡展示与三张盖卡洗切；双端最终可见状态确认两张魔陷卡在墓地、原怪兽仍为里侧守备。事件与状态并不单独证明破坏因果。

## 局限

隐藏排列无法作为公开覆盖目标，`coverage: []` 只表示单次采样通过；两次不同格子也不能证明所有排列。GUI 目视回放、Windows 构建与真实模型决策未验证。
