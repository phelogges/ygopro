# 录制复盘场景 duel-002

来源为本机录制 `8ed56016e03248fd8e0f1807e025fab1` 的已验证编译稿。原始双端日志及修复记录留在 `out/duel-recordings/`，本目录只保存回归所需的 YAML 与双方实际使用的 YDK。Host 共 135 步，Guest 共 126 步；双方按“不洗牌”房间配置进行单局 1v1，预期自然终局为 Host 获胜。

类型为严格场景（schema v1）。[goal.md](goal.md) 明确原始目标没有在录制前单独保存，当前目标是事后重建。逐项审核结论：

| 目标 | 结论 | 证据边界 |
| --- | --- | --- |
| 复现双方提示与语义动作 | 已验证 | 135/126 步双客户端回放完成 |
| 可见区域与公开展示事件 | 已验证 | 场景断言及 `event_assertions` 通过；只代表写入的观察项 |
| 双方一致确认 Host 自然获胜 | 已验证 | 终局目标及双端权威赢家一致 |
| 未列入断言的卡片效果因果 | 未验证 | 回放不会从状态变化自行推导效果原因 |

```sh
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py \
  --scenario tests/scenarios/duel-002/scenario.yaml --timeout 300
```

原编译稿的 30 处魔陷区 `position: unknown` 来自旧客户端将通用正面和通用里侧位掩码合并为 `unknown` 的序列化方式。本场景以当前客户端同一步的可见快照重新核对，写成 28 处 `face_up` 和 2 处 `face_down`；卡片 ID、控制方、区域和序号断言保持原编译稿语义。`allowed_random_events: [hand_shuffle]` 是原录制中发生的手牌洗切例外。最终文件两端完整回放通过，报告为 `out/agent-e2e-runs/1791348511-48911/scenario-report.json`。

2026-10-09 又完整运行一次双客户端无头回放，双方正常终局，Host 获胜；新报告为 `out/agent-e2e-runs/1791520794-8176/scenario-report.json`。Windows 未验证。
