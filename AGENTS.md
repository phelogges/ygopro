# 仓库工作约定

本文件面向在本仓库工作的编码 Agent。先从 [文档总索引](docs/README.md)找到现行契约和设计，再阅读相关源码；让实现、契约和验证结果保持一致。旧版本文档保留演进与测试用途，不作为当前正式服务的默认入口。

## 项目与范围

- 本项目是《游戏王》对战客户端及游戏引擎的开源实现。Agent 功能分两期：一期完成客户端可见状态与动作协议的语义转换；二期实现调用 LLM 和运行时技能的 Agent 服务。当前先在 macOS 完成两期实现，Windows 构建与验证放到最后；最终仍须报告两个平台各自的验证结果。
- 当前目标是单局 1v1，人工完成建房、入房和选卡组，Agent 从赛前选择接管至对局结束。三局两胜及换备牌为 TODO；双打、观战、单机残局不在当前范围。中文优先，其他语言为 TODO。
- `gframe/` 是客户端与 Agent 接入重点，`ocgcore/` 是游戏引擎，`script/` 是卡片 Lua 脚本。为 Agent 功能不得修改游戏服务端实现或既有 CTOS/STOC 联网协议；`ocgcore/` 与 `script/` 默认不改，若独立缺陷确需修改，先说明原因和影响。

## 协议与职责

- 客户端只向 Agent 服务发送本方可见状态、提示和合法候选；不得泄露隐藏卡身份。卡片静态资料由二期 Agent 使用卡片 ID 查询，客户端不复制卡名或效果文本。
- `agent_sdk/` 将结构化意图校验并翻译为语义动作；客户端再次核对会话、提示、候选与参数，然后使用原有响应编码。LLM 不得直接生成 CTOS 字节或绕过客户端校验。
- 改动请求、响应、候选含义、动作映射或工具行为时，同步检查并更新现行 `docs/contracts/`、相关设计及对应测试；将实际验证的日期、平台、路径、结果和未验证项写入 `docs/validation/`。操作步骤放在 `docs/guides/`。正式服务先读 [HTTP v3](docs/contracts/agent-http-v3.md)、[动作契约](docs/contracts/duel-actions.md)、[工具契约](docs/contracts/agent-tools-v1.md) 和 [现行状态设计](docs/design/agent-state.md)；固定牌序回归另读 [场景 v1](docs/contracts/agent-scenario-v1.md)，随机场景读 [场景 v2](docs/contracts/agent-scenario-v2.md)，人工对局录制读 [录制契约](docs/contracts/duel-recording-v1.md)。发现代码与现行契约有行为差异时，先列出差异与影响并和用户讨论处理，不能静默改写任一方。

## 构建与验证

- 新开发只使用 CMake Presets + vcpkg，参见 [CMAKE_BUILD.md](CMAKE_BUILD.md) 与 `CMakePresets.json`。不要为新功能编辑或验证 premake 构建。上游仍使用 premake：同步上游时正常合并相关文件，无须对 premake 做额外验证。
- 客户端使用 C++17，遵循现有代码风格并用 clang-format 格式化所改代码。Python 使用 3.12，默认以 uv 管理依赖，并用 Ruff、Pyright 检查。二期服务实现见 [二期设计](docs/design/agent-phase-2.md)；新增客户端依赖前说明必要性。
- macOS 常用入口：`cmake --preset MacOS-Debug`、`cmake --build --preset MacOS-Debug`、`ctest --test-dir out/build/MacOS-Debug --output-on-failure`。Python 检查入口见 [agent_sdk/README.md](agent_sdk/README.md)。涉及真实决策或对局流程的改动，运行 `python3.12 tools/agent-e2e.py --games 3 --deck deck/test/test.ydk`；该入口和 `--scenario` 默认走 Agent HTTP v3，`--protocol v2` 只做历史兼容回归。步骤见 [回归指南](docs/guides/scenario-replay.md)，最近实测证据见 [验证总览](docs/validation/README.md)。按改动风险选择验证，文档小改不必重跑三局；文档更新运行 `python3 tools/check-docs.py`。
- 编译或契约测试通过不等于真实双客户端对局通过。GUI 人工接管、超时和断线需分别报告实测情况；未执行的平台或路径明确标为未验证。

## 本地资源与 Git

- `.agents/skills/ocg-rulebook/` 与 `.agents/skills/ygo-card-db/` 是二期 Agent 查询规则和卡片的运行时资源，纳入 Git 管理；需要相关事实时使用它们。`ygo-card-db` 与客户端共用项目或发布包主目录的 `cards.cdb`，不在技能目录维护数据库副本。`third_party/irrlicht/`、`third_party/miniaudio/` 是用户管理的本地依赖资源，未经明确指示不编辑或提交。
- `system.conf` 是已跟踪的运行配置，客户端启动可能改写它。不要暂存或提交其运行时变化，也不要为清理工作区擅自覆盖用户配置。
- 密钥、模型端点、个人路径、卡库副本、诊断日志和对局轨迹只放本地配置或忽略目录，不写入提交或契约示例；文档使用占位值，测试夹具使用可公开的构造数据。提交前精准暂存并检查 `git diff --cached --name-only`；不要顺手加入生成物或用户管理目录。
- `origin/master` 用于同步上游，开发在 `dev`。合并上游发生冲突时，先列出冲突点与影响，和用户讨论解决方式；不得借合并修改游戏服务端或擅自重写上游构建文件。
