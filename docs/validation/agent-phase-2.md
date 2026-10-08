# 二期 Agent 服务验证记录

## 已执行的离线验证

- macOS CMake Debug 客户端构建成功；`ctest` 的 `agent_codec` 与 `agent_codec_sdk_contract` 通过。
- `agent_sdk` 78 项 unittest 通过。服务端 15 项测试覆盖状态持久化与重启、重传冲突、查询失败、回执、人类只读接口、Pydantic AI 结构化输出、Monty 卡库工具、客户端查询往返和启动能力探测。
- `agent_server` Ruff 与 Pyright 通过；`ygo-card-db` 的查询脚本 223 项检查通过，规则书资源由服务端工具测试读取。
- v3 无头双客户端局域网对战完成两局：双方都加载 `deck/test/test.ydk`。首次主客端分别提交 33、31 次决策；修正客户端回执队列后复跑，分别提交 152、69 次决策，双方均收到终局且胜者一致。复跑中的 221 个不同动作 ID 对应 222 次回执提交尝试，其中一次因 HTTP 客户端忙而即时重试。诊断日志保留在忽略目录 `out/agent-e2e-runs/1791366856-99434/` 与 `out/agent-e2e-runs/1791367245-6460/`。这是确定性假策略验证，不证明真实模型的决策质量。
- macOS 发布目录 `out/release-verified/ygopro-agent-macos-0.1.0/` 与同名 zip 已生成并通过静态校验；独立 `agent-server` 程序从发布根启动并通过 `/v3/ready` 的令牌与 nonce 检查，`--check-resources` 成功读取发布根技能和卡库。构建过程曾发现 PyInstaller 缺少 `genai_prices` 与 `pydantic_ai_slim` 元数据，已修复打包参数并复测。
- 配置与本地数据统一迁移到 `.agents/` 后，重新运行服务端 15 项测试、发布布局 4 项测试、CMake Debug 构建和 `ctest` 2 项，均通过。v3 无头双客户端又完成一局，双方正常结束；诊断日志在 `out/agent-e2e-runs/1791368320-25716/`。新发布目录 `out/release-agents/ygopro-agent-macos-0.1.0/` 与 zip 通过静态校验，独立 `agent-server --check-resources` 通过；zip 含 `.agents/config.toml`，无旧 `.agent/` 或本地 `.agents/data/`。

## 仍需执行

- 用户提供真实 OpenAI Responses 风格端点、模型名和密钥环境变量后，验证启动能力探测、实际模型工具调用和至少一局对战。
- Windows 构建、独立进程和双客户端验证放在最后；目前未执行。
- GUI 双客户端实际模型对战、超时与断线人工接管仍需分别实测。既有一期 GUI 剧本验证不等于二期模型链路验证。

## 真实端点启动探测（2026-10-08）

- 本地配置的 Responses 兼容端点在 thinking 模式下拒绝强制工具选择。为模型配置加入 `supports_forced_tool_choice` 开关；本地配置设为 `false` 后，实际端点通过工具调用与结构化输出能力探测。服务端 31 项测试、Ruff、Pyright 通过。
- 一端普通 GUI 客户端与一端 Agent GUI 客户端已启动；Agent 子进程只读观察接口返回 200。此时尚未建房和决斗，因此不将其记为真实对局通过。当前开发客户端使用源码环境服务，既有发布包尚未重建以包含此兼容开关。

## 真实双客户端对局中的历史中断（2026-10-08）

- Agent GUI 客户端在一次 `MSG_SELECT_IDLECMD` 前报告本地 `history_incomplete`，没有向模型发送该提示。对本方入站游戏消息逐条核对后，首次未解析消息为长度 10 的 `MSG_CARD_HINT`（消息类型 160，`CHINT_DESC_ADD`）；普通客户端会处理该卡片提示。客户端将其当未知关键消息而停止自动决策，符合现有失败保护，但暴露了事件解析覆盖遗漏。
- 已增加 `MSG_CARD_HINT` 与 `MSG_PLAYER_HINT` 的结构化事件；卡片提示仅在关联卡片当前可见且身份已知时入历史，不向 Agent 暴露隐藏卡提示值。已知卡片的当前提示也进入快照，以覆盖隐藏期间收到提示、后来变得可见的情况。更新了 v2/v3 共用的观测事件契约。macOS Debug 客户端构建、`ctest` 两项、Agent SDK 80 项、Agent 服务端 33 项测试通过；Ruff 与 Pyright 通过。
- 对后续未覆盖或截断的游戏消息，客户端诊断日志新增 `event_decode_incomplete`（仅消息类型与长度）；事件队列溢出记录 `event_queue_overflow`。这样下次可直接定位缺口，仍不向模型发送原始游戏包。
- 当前运行中的 GUI 进程不会加载新二进制，需在新对局中重启 Agent 客户端并再次触发同类提示验证。此前这局已经标记历史不完整，不能靠快照把缺失事件恢复为完整历史；不计为真实模型完整对局通过。
- 静态审计还发现若干对局内消息尚未结构化，包括牌顶公开、区域交换与洗牌、随机选中、装备与目标关系、指示物变化及投掷结果。它们不能简单归为“无用消息”：部分原始包含隐藏牌身份或位置映射，须逐项确认本端可见语义后补事件和测试。当前遇到这些消息仍会安全中止自动决策，并通过新诊断日志报出类型和长度。

## 可观测性扩展（2026-10-07）

- 新增按配置档隔离的 SQLite 轨迹、只读查看令牌、静态对话页面、分页与 SSE 实时流、卡名补充、单局 JSON 导出、只读历史模式、已结束对局保留与本地手动删除。接口与信息边界见[契约](../contracts/agent-observability-v1.md)。
- 服务端 30 项测试通过，覆盖流式模型响应、推理字段过滤、页面授权、SSE 游标、导出、外部写入后的只读视图刷新、保留与中断标记；Ruff、Pyright 均通过，`node --check` 页面脚本通过。服务端测试中的 HTTP 端口需要本机回环绑定权限。
- 一局 v3 离线双客户端对战正常结束，主方 71 次、客方 31 次提示均记录动作签发与客户端回执，双方各记录一条 `duel_finished`；诊断目录为 `out/agent-e2e-runs/1791384050-50629/`。这是离线确定性策略，因此没有供应商推理文本，不能验证真实模型的推理摘要粒度或战术表现。
- macOS 最终发布目录和 zip 位于 `out/release-observability-v1/`；发行脚本的布局与哈希验证通过，独立 `agent-server --check-resources` 成功读取页面、技能与卡库。开发服务的 `--view-only --legacy --config config --port 7951` 实际启动后，`/view` 返回 200、决策就绪接口返回 404、无令牌的数据请求返回 401，随后正常停止。Windows 与真实模型端点仍待后续验证。
