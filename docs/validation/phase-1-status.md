# 第一期验证状态

> 状态：历史验证记录；截至一期 v2 回归。现行验证范围见[验证总览](README.md)；正式 Agent 服务现行协议见[HTTP v3 契约](../contracts/agent-http-v3.md)。

## v2 状态协议当前实现

当时客户端与确定性测试端已接入 `/v2/decision`、事件分批 `/v2/sync` 以及 F10 恢复用 `/v2/status`。决策携完整本方可见快照和未确认事件；测试端的 `StateJournal` 对每次请求保存一份原子完整检查点，提供状态版本、事件确认和确定性净差异。客户端当时已按可查看权限过滤区域身份，并对区域未确认的动态数值省略字段。具体字段与失败语义见 [v2 契约](../contracts/agent-http-v2.md)。以下“二期未实现”的表述仅指这一历史验证时点，二期后续结果见[验证总览](README.md)。

本轮 v2 修改在 macOS 通过 CMake 构建、CTest 2/2、Python SDK 78 项测试、Ruff 和 Pyright。真实 LAN 回环下，两客户端连续三局无头对局均从赛前选择走到双方确认的终局；六端各自的决策请求与提交数相等，均无 `agent_error`，每局的终局事件均由 `/v2/sync` 返回 HTTP 200。记录在 `out/agent-e2e-runs/1791347108-24975/`。固定牌序 `summon-chain` 场景通过 8 次决策和最终检查点，记录在 `out/agent-e2e-runs/1791347429-30481/scenario-report.json`。

同轮发现并修正两种公开卡位置校验问题：墓地卡片查询字段可与 `position: "unknown"` 同时出现；通用 `POS_FACEUP` 应序列化为 `face_up`，不能误写成 `unknown`。测试服务另已接受 `control_changed` 的 `source` 与布尔 `agent` 字段，并拒绝同名字段用于游戏消息。本轮三局对局发生在通用位置修复之前，修复后的真实固定牌序场景已通过。下列既有记录是此前 v1／场景功能的历史验证。

`duel-001` 曾在 Host 步骤 48 因缺少 `53927851` 的反制候选停止，见 `out/agent-e2e-runs/1791347524-32101/scenario-report.json`。对比历史通过报告与当前起手，确定原因是共享 `deck/test/guest1.ydk` 的牌序后来改变：Guest 起手已没有 `12375297` 和 `27204311`，所以未能发动剧本要求的 `56651978`，Host 也就等不到反制时点。场景现使用自己的 `guest.ydk` 固定历史验证过的前五张及下次抽牌；重新运行所有步骤后双方终局一致，Guest 获胜，见 `out/agent-e2e-runs/1791348155-42920/scenario-report.json`。共享卡组与引擎均未修改。

人工录制 `8ed56016e03248fd8e0f1807e025fab1` 已作为 `tests/scenarios/duel-002/` 入库。录制编译稿的 30 处魔陷 `position: unknown` 在当前 v2 客户端中按同一决策的可见快照恢复为 28 处 `face_up` 和 2 处 `face_down`；其余剧本步骤与两副 YDK 保持原样。先在不检查旧模糊表示的条件下完整复盘，再用恢复精确断言的最终文件复盘，两次均执行 Host 135 步、Guest 126 步并得到双方一致的 Host 自然获胜终局。最终报告在 `out/agent-e2e-runs/1791348511-48911/scenario-report.json`。该长剧本在当前完整检查点实现上耗时约 156 秒，运行命令使用 `--timeout 300`；120 秒总时限会在接近终局时超时，并非动作错误。

## 已验证

- macOS `cmake --preset MacOS-Debug`、`cmake --build --preset MacOS-Debug` 成功。
- CTest 的 `agent_codec` 覆盖 20 类决斗提示、赛前选择、非法动作和截断消息；`agent_codec_sdk_contract` 将 C++ 生成的 22 个提示交给 Python SDK 解析。
- Python SDK、场景解释器与 HTTP 测试端共 41 项单元及本机 HTTP 测试通过；限定 `agent_sdk/` 范围的 Ruff、Pyright 通过。
- macOS Null driver 下的真实 LAN 回环验收：两个独立客户端进程、同一测试端、双方加载 `deck/test/test.ydk`，连续三局从赛前选择完成至权威 `MSG_WIN` 和 `STOC_DUEL_END`。三局两端赢家一致，没有 Agent 错误或人工操作；每端 Agent 决策提交数加客户端空窗口自动放弃数，与出站动作包数一致；双方各自三局的初始五张手牌均不同。诊断记录位于 `out/agent-e2e-runs/1791206682-5526/`。
- 固定牌序场景：双端加载同一 `deck/test/test.ydk` 时，前五张起手和场景断言一致，见 `out/agent-e2e-runs/1791206670-5307/scenario-report.json`；分别加载 `tests/scenarios/summon-chain/host.ydk` 与 `guest.ydk` 时，真实 LAN 对局完成通常召唤、魔法发动与连锁，8 次脚本决策后双方可见状态达到检查点，见 `out/agent-e2e-runs/1791206869-8765/scenario-report.json`。后一场景的双方各有 4 次空连锁窗口由客户端自动放弃，Agent 决策请求中没有仅含放弃候选的窗口。故意设置错误手牌断言的场景按预期失败并写出具体差异，见 `out/agent-e2e-runs/1791198254-3012/scenario-report.json`。
- `duel-001` 复杂场景：macOS 真实双客户端 LAN 对局完成固定起手、两回合展开、三段诱发连锁、尼比鲁、同调召唤与 Host 投降；两端均收到决斗结束，Guest 获胜，见 `out/agent-e2e-runs/1791223251-61194/scenario-report.json`。Host 场景卡组因剧本需两张派比安而复制并补充原 `host1.ydk`，详见 `docs/design/duel-001-e2e.md`。Windows 尚未验证。
- GUI 场景验证：macOS 双可见窗口运行 `duel-001`，默认 1 秒观看延迟下 Guest 获胜，Host 投降，两端均完成权威终局校验，见 `out/agent-e2e-runs/1791224585-84268/scenario-report.json`。129 次服务请求中 55 次为自动放弃的可选提示，74 次明确脚本动作加入观看延迟；客户端运行约 138 秒，命令返回后两个窗口进程仍在。另以固定起手检查点验证 GUI 窗口保留，见 `out/agent-e2e-runs/1791224527-83208/scenario-report.json`。Windows GUI 未验证。
- GUI 失败路径：使用临时构造的错误卡片选择器触发首个主阶段步骤不匹配，命令返回非零并写出合法候选，两个窗口仍保留现场；见 `out/agent-e2e-runs/1791225012-91476/scenario-report.json`。这次临时窗口随后已关闭。
- GUI 窗口清理修复后：macOS `summon-chain` 可见双客户端场景完成 8 次决策并到达检查点，见 `out/agent-e2e-runs/1791225310-96656/scenario-report.json`；`duel-001` 再次完成完整对局，两端均收到终局，Guest 获胜，见 `out/agent-e2e-runs/1791225410-98403/scenario-report.json`。构建、CTest 2/2 和 `git diff --check` 通过。用户完整观看双客户端对局，确认主菜单和提示弹窗均正确关闭，GUI 测试效果符合预期；随后手动关闭两个客户端进程。
- Python SDK 与场景解释器共 41 项测试通过；限定范围的 Ruff、Pyright 通过。

## 待实战验证

- Windows `VS2026-x64-Debug` 预设构建与双客户端对局。
- GUI 模式下的人工 F10 接管、超时与断线后的救场需要桌面交互验收；当前无界面回归覆盖自动对局和数据过滤。
- 固定牌序场景只控制起手及后续卡组牌序，不控制引擎全部随机事件。

桌面自动化权限未获批准，因此此前 GUI 人工接管路径未用 Computer Use 测试。回归采用客户端内的非 UI 测试入口，经过真实本机服务端与 CTOS/STOC 网络，不需要窗口操作。诊断可通过 `YGOPRO_AGENT_LOG_PATH` 保留本机 JSONL 原始帧与决策记录。v2 的终局 `/v2/sync` 路径已在本轮六个客户端实例中验证；人工 F10 恢复仍待 GUI 交互验收。
