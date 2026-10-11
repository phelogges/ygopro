# 魔导战士 破坏者③破坏魔陷卡录制与回放

> 状态：历史验证记录，截至 2026-10-11；经用户审核的场景已收入 [`tests/scenarios/breaker-spell-trap-destroy/`](../../tests/scenarios/breaker-spell-trap-destroy/README.md)。现行场景字段见[固定场景契约](../contracts/agent-scenario-v1.md)，可见状态字段见[HTTP v3 契约](../contracts/agent-http-v3.md)。

人工双客户端录制 `d90bb9206e6c409ba3baf499995d742f` 使用单局 1v1、不洗牌、起手五张、LP 8000、每回合抽一张和无限时设置；双端日志、实际提交的 YDK 及编译报告完整。草稿共 7 个 Guest 决策步骤、0 个 Host 决策步骤，终局是 Host 投降、Guest 获胜。

原始录制中，Guest 盖放 00059080 至己方魔陷区序号 1，召唤 71413901 至怪兽区序号 0。其召唤后效果增加 1 个指示物，随后 Guest 发动 `description_id=1142622418` 的③效果、移除指示物并选择盖卡。双方可见的移动消息将该格的卡送至墓地，原始 `reason_flags=65`，含 `REASON_DESTROY` 与 `REASON_EFFECT`；结算后墓地公开为 00059080。Host 在选取前只看到对方该格的里侧卡，断言没有从 Guest 日志补入 Host 当时未知的身份。

首轮自动回放 `out/agent-e2e-runs/1791659175-10227/scenario-report.json` 失败于 `invalid_state`：客户端将 `std::map<int,int>` 指示物直接编码成 `[[1,1]]`，Agent 状态层要求十进制字符串键的 JSON 对象。经用户确认，客户端改为 `{"1":1}`，并在 v2 可见字段契约中明确形状，v3 继承该字段。macOS Debug 重建成功。加入双端 `effect_activated` 的 `description_id`、`counter_removed`、`card_moved` 路径与 `reason_flags=65` 断言后，HTTP v3 回放报告 `out/agent-e2e-runs/1791659690-21811/scenario-report.json` 为 `passed`、`duel_finished`，双方步骤耗尽。场景单元测试 32 项、文档检查 53 页通过。

经用户审核收录后，运行 `agent_sdk/.venv/bin/python tools/agent-e2e.py --scenario-dir`；汇总报告 `out/agent-e2e-runs/batch-1791660037-29869/batch-report.json` 为 `total: 9`、`passed: 9`、`failed: 0`、`unsupported: 0`。本场景对应 `scenario-002.json`，状态 `passed`。随机的魔术礼帽场景按其声明的采样目标运行，批量通过不代表所有隐藏排列已覆盖。

这验证了本局③效果的可见事件与破坏结果，也覆盖了有指示物怪兽的状态序列化。未运行真实模型、GUI 回放或 Windows 构建。
