# 人工双客户端决斗录制指南

> 状态：现行操作指南；适用于 macOS 开发环境。权威字段与失败语义见[录制契约](../contracts/duel-recording-v1.md)，执行证据见[录制验证记录](../validation/manual-duel-capture.md)。

从仓库根目录使用已构建的 macOS 客户端和 Python 3.12 环境：

```sh
cmake --preset MacOS-Debug
cmake --build --preset MacOS-Debug
uv run --project agent_sdk --extra scenario python tools/record-duel.py --name "示例对局"
```

默认是严格确定性场景。启动器打开 Host、Guest 两个正常 GUI 窗口。人工在 Host 建立单局 1v1 房间，启用“不洗牌”，使用起手五张、LP 8000、每回合抽一张且无时间限制；“不检查卡组”可开可关。Guest 加入该房间，双方选好卡组并手动决斗至终局。启动器从实际提交的卡组、双端提示和响应编译场景，然后运行一次无界面双客户端回归。客户端录制与回归都使用现有局域网协议，服务端实现不变。

测试目标先由开发 Agent 写成含“用户原话”和“Agent 整理目标”的 `goal.md`，再用 `--goal-file PATH` 在打开 GUI 前归档。若目标是抛币、掷骰或随机选卡，显式追加 `--scenario-kind random`；仍须勾选“不洗牌”。随机模式结束后只产 `draft/scenario.unverified.yaml` 和 `review_required` 清单，等待 Agent 按[随机场景契约](../contracts/agent-scenario-v2.md)裁切到效果完成后的 checkpoint 并补断言，不能直接当作通过的回归。

原始 `host.jsonl`、`guest.jsonl`、进程日志、`manifest.json` 与生成草稿保存在 `out/duel-recordings/<record_id>/`。`draft/scenario.yaml`、两端 YDK、中文 `timeline.md` 是待验证产物；`draft/compile-report.json` 说明能否编译，`validation-report.json` 与 `validation.log` 记录实际回归结果。只有 `manifest.json` 和 `validation-report.json` 都为 `validated` 才认为 YAML 通过回放。命令结束时打印绝对路径，窗口默认保留，`--close-clients` 可让启动器关闭本次启动的窗口。`--max-log-mib` 调整每端日志大小上限，默认 100。录制数据含双方隐藏信息，不提交到 Git。

查找、查看大小或显式删除录制：

```sh
python3.12 tools/duel-recordings.py list --limit 10
python3.12 tools/duel-recordings.py latest
python3.12 tools/duel-recordings.py delete <record_id> --yes
```

删除前省略 `--yes` 会先显示目标信息而不删除。`list` 中的 `interrupted` 表示清单仍处于录制中，但启动的客户端进程已不存在。录制工具不会自动删除旧记录。

编译器目前自动把同形候选写为序号和预期匹配数量，`draft/compile-report.json` 的 `ordinal_usages` 列出这些步骤。回放失败时根据角色、响应序号和候选信息审阅。旧版录制的人工覆盖文件 `overrides.json` 仍可读取，并会校验其内容。需要单独重新编译或回放时执行：

```sh
uv run --project agent_sdk --extra scenario python tools/compile-duel-recording.py --recording out/duel-recordings/<record_id> --output out/duel-recordings/<record_id>/draft
uv run --project agent_sdk --extra scenario python tools/agent-e2e.py --scenario out/duel-recordings/<record_id>/draft/scenario.yaml
```

旧版序号覆盖若过期或未使用，编译器会拒绝。日志截断、缺一端、房间参数不符、未知提示、异常终局或回归首次偏差均保持失败状态和诊断。已有 `.yrp` 无法直接用于本入口。

仅对已经存在的历史录制，若房间开启了洗牌或发生掷骰等无法控制的随机事件，可以离线提取仅供分析的草稿：

```sh
uv run --project agent_sdk --extra scenario python tools/compile-duel-recording.py --recording out/duel-recordings/<record_id> --output out/duel-recordings/<record_id>/draft --analysis-draft
```

此时查看 `draft/scenario.unverified.yaml`、`draft/timeline.md` 和 `draft/compile-report.json`。`draft_unverified` 不是回归通过，不能直接把这份 YAML 当作固定牌序测试用例。新标准入口有显式的随机场景模式，但依然要求“不洗牌”；未开启时应在开局前报错并关闭本次启动的两个 GUI。历史分析命令不能替代新随机录制模式。

旧版本录制器若报告 `unpaired_response`，保留原始日志，并使用 CMake Debug 构建出的 `agent_response_decode` 与 `tools/repair-duel-recording.py --recording <原录制目录> --output <独立修复目录>` 重新配对。工具只在每条入站决策帧恰有一个提示或空连锁、一个实际出站响应时继续，并由原始决策编解码器逐字节反解。`repair-report.json` 列出修复数量；对修复目录重新编译和回归，不覆盖原始日志。新录制器已修复空连锁响应的暂存错误。
