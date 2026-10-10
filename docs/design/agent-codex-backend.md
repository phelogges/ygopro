# Codex Agent 后端设计

> 状态：现行设计。适用于可选 Codex 后端；共用服务设计见[二期服务设计](agent-phase-2.md)，协议以 [HTTP v3 契约](../contracts/agent-http-v3.md)为准。

## 背景与边界

在现有 [二期服务](agent-phase-2.md)中增加可选 `codex` 后端；未指定后端时继续使用 Pydantic AI。两种后端共用客户端 [HTTP v3](../contracts/agent-http-v3.md)、权威状态镜像、事件日志、人类观察页面和 `agent_sdk` 语义动作校验。一次客户端进程只选一种后端。客户端与游戏服务端的联网协议、游戏服务端实现、`ocgcore` 和卡片脚本均不因后端选择而改变。

Codex 使用官方 Python `openai-codex` SDK 管理本地 Codex 运行时。SDK 发布包带有固定版本的 CLI 运行时依赖；默认由 SDK 定位，不约定 `site-packages` 中的实际文件路径，也不要求用户准备 `.agents/bin/codex`。仅在将来确需覆盖运行时时才显式设置 `codex_bin`。这不改变运行时所需的 ChatGPT 登录和模型访问条件。[Codex SDK 官方文档](https://learn.chatgpt.com/docs/codex-sdk)

## 运行拓扑与生命周期

```text
gframe ── HTTP v3 ── agent_server ── 官方 Python SDK ── 本地 Codex app-server
                         │                  │
                         ├─ 状态与轨迹 SQLite └─ 受限 MCP stdio 子进程
                         ├─ agent_sdk              │
                         └─ 人类只读页面       本地鉴权 IPC ── 服务端工具执行器
```

一个 Agent 客户端启动一个服务进程；选择 Codex 后端时，它在客户端启动阶段启动一个 Codex 子进程并检查登录及必需能力。一局使用一个持久 Codex thread，每次真实决策是一轮 turn。服务在 SQLite 中保存 `(session_id, duel_id)` 与 thread ID 的映射；重启后只恢复已确认的事实和 thread，不恢复已中断的模型栈或过期提示。终局、人工接管、提示撤销和超时中断相应 turn；收到权威 `duel_ended` 时不再签发动作，并归档该局 Codex thread。SDK 的归档不物理删除其原生会话文件，后续如需彻底清除需单独制定受支持的清理方法。登录失效、额度受限或模型故障计入既有失败计数，达到配置阈值后交还人工，决斗中不启动登录流程。

应用配置档负责 `backend`、业务预算、超时、端口和持久化路径；缺省后端为 `pydantic_ai`。仅 Pydantic AI 路径要求 OpenAI 风格端点及其密钥。Codex 路径仅使用本地 ChatGPT 登录；模型和推理强度由用户在独立的 `codex_home/config.toml` 中按 Codex 自身格式管理，不在应用配置或客户端界面重复配置。无需预先创建该文件，也不随发布包生成模板。初始化工具创建隔离目录、检查登录状态，未登录时引导用户按 SDK 支持的浏览器或设备码方式登录；常规客户端启动不得在决斗中等待交互登录。

## 目录和技能隔离

开发根或发行根记为 `<root>`；每个配置档的 Codex 数据位于 `<root>/.agents/data/<profile>/codex/`，其下分别有 `codex_home/` 和 `workspace/`。启动 Codex 子进程时同时设置 `CODEX_HOME` 与 `HOME` 到 `codex_home/`，工作目录固定为 `workspace/`，并以专用根标记阻止工作目录向上发现项目根。运行时覆盖配置关闭项目 `AGENTS.md` 注入、通用 Shell、Web 搜索和子 Agent，并只启用本服务提供的 MCP 工具；与用户手写 Codex 配置冲突时启动失败，不悄悄放宽权限。隔离效果需要离线检查与真实运行审计，不能只凭路径约定宣称已隔离。Codex 对项目指令、配置及技能的发现规则见[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)和[官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

两个后端共同使用 `<root>/.agents/skills/ocg-rulebook/` 与 `<root>/.agents/skills/ygo-card-db/`，不复制第二份技能。Codex 在受控输入中显式引用这两个原始 `SKILL.md`；具体规则和卡片查询经 MCP 调用服务端现有技能资源层，卡片数据仍取 `<root>/cards.cdb`。不从用户全局技能目录、其他项目或个人 `HOME` 读取业务技能。技能文档不是工具权限边界；每次 MCP 调用仍须校验本局、视角、状态版本、预算和输出大小。

## 决策、工具与验证

首轮输入沿用既有系统指令、已确认完整状态及本方卡组目录；后续输入沿用有序新事件、状态差异、当前提示和完整合法候选。Codex 可以经 MCP 查询当前场面、区域、卡片、分页历史、规则、卡库与本方牌表；这些场面和历史工具读取服务端已确认镜像。旧版推断笔记不再作为独立字段注入新决策，也不提供读写工具。另提供受限的确定性算术和数值比较工具，不开放任意 Python 执行。MCP stdio 进程只作转发，通过本地鉴权 IPC 请求父服务的工具执行器；IPC 凭据、决策绑定和期限均由父服务核验。HTTP v3 的 `inspect_zone` / `inspect_card` 客户端往返保留作兼容和诊断，当前不向 Codex 暴露。

Codex 只配置一个 `ygopro_duel` MCP 服务，而不是每个业务工具各启动一个服务。该 MCP 的 `tools/list` 公布工具名称、描述和参数格式；其调用适配层与 Pydantic AI 的 `@agent.tool` 函数共用服务端资源与状态实现，不把 Pydantic AI 的函数直接注册到 Codex。两端均暴露同一受限 `calculate` 工具，其十进制实现位于共用执行层；Pydantic AI 还可以通过本地 CodeMode 在受限 Python 表达式中做计算。共用能力的语义与校验应保持一致，新增能力时按[二期工具约定](agent-phase-2.md#工具与沙盒)检查双端入口。

共用的工具执行类为 `agent_server/duel_tools.py` 中的 `DuelTools`。MCP 桥接层保留工具公布、传输鉴权和参数类型检查；所有工具经 `DuelTools` 执行，与 Pydantic AI 注册函数走相同的方法。每次调用显式传入当前决策上下文，避免持久 MCP 连接误用其他提示或对局的状态。

模型最终输出结构化 `{reason, intent}`。Codex 的输出 JSON Schema 按当前提示生成封闭的动作形状，随后仍由 `agent_sdk` 与当前合法候选校验并翻译，客户端再校验并使用原有响应编码。无效输出或非法意图按现有尝试上限重试，然后交还人工；Codex 不生成 CTOS/STOC 字节。总期限、宿主工具调用、客户端查询和重试次数继续硬限制；SDK 内部模型请求数若无法可靠计量，只作观测指标，不伪称与 Pydantic AI 的 `model_requests` 等价。上下文接近配置阈值时使用 Codex 原生压缩，并保留 SQLite 权威状态和完整历史作为重新查询来源。

观察页面继续按单局展示请求、响应、工具与耗时。只记录 SDK 实际提供的推理内容或摘要；模型没有返回完整内部思考时，界面明确显示不可得，不构造思考文本。Codex Hooks 不承担业务校验或观测核心链路。

## 发布与验证边界

`agent_server/uv.lock` 锁定 SDK 与其配套运行时版本。发版应验证服务可在无额外下载的环境中定位并启动运行时；若采用单文件 PyInstaller，需专门验证其对 SDK 运行时依赖的收集、进程启动及资源路径，不把 Python 依赖安装成功等同于发行包成功。发行包不含登录凭据、个人 `codex_home`、会话或日志；用户在发布根执行初始化并登录。macOS 优先完成；Windows 的 IPC、运行时打包、登录和 GUI 对局最后独立验证。

实现顺序与验收矩阵见 [Codex 后端验证](../validation/agent-codex-backend.md)。离线假 SDK / 假 MCP 验证不代表真实 Codex 决策或双客户端决斗已经通过。
