# 人工对局录制验证

本页给出当前入口和已完成的验证；契约与边界见 [录制契约](../contracts/duel-recording-v1.md) 和 [设计](../design/manual-duel-capture.md)。普通人工 GUI 录制的新启动路径仍须由用户再跑一局验收。

从仓库根目录使用已构建的 macOS 客户端和 Python 3.12 环境：

```sh
cmake --preset MacOS-Debug
cmake --build --preset MacOS-Debug
uv run --project agent_sdk --extra scenario python tools/record-duel.py --name "示例对局"
```

启动器打开 Host、Guest 两个正常 GUI 窗口。人工在 Host 建立单局 1v1 房间，启用“不洗牌”，使用起手五张、LP 8000、每回合抽一张且无时间限制；“不检查卡组”可开可关。Guest 加入该房间，双方选好卡组并手动决斗至终局。启动器从实际提交的卡组、双端提示和响应编译场景，然后运行一次无界面双客户端回归。客户端录制与回归都使用现有局域网协议，服务端实现不变。

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

此时查看 `draft/scenario.unverified.yaml`、`draft/timeline.md` 和 `draft/compile-report.json`。`draft_unverified` 不是回归通过，不能直接把这份 YAML 当作固定牌序测试用例。新标准录制入口只允许确定性录制，未开启“不洗牌”应在开局前报错并关闭本次启动的两个 GUI；历史分析命令不能视为新录制模式。

旧版本录制器若报告 `unpaired_response`，保留原始日志，并使用 CMake Debug 构建出的 `agent_response_decode` 与 `tools/repair-duel-recording.py --recording <原录制目录> --output <独立修复目录>` 重新配对。工具只在每条入站决策帧恰有一个提示或空连锁、一个实际出站响应时继续，并由原始决策编解码器逐字节反解。`repair-report.json` 列出修复数量；对修复目录重新编译和回归，不覆盖原始日志。新录制器已修复空连锁响应的暂存错误。

## 新规范验收项

下面区分已完成的自动验证和仍需人工 GUI 操作的验收。单元测试及脚本驱动的无头对局不能冒充手动建房、点击与结算窗口验收。

| 场景 | 预期 |
| --- | --- |
| 标准双端人工 GUI 录制 | UUID 与名称可查询；双端 JSONL、清单、中文时间线、YDK、YAML 和回放报告齐全；状态只有回放通过才为 `validated` |
| Host 忘记开启“不洗牌” | 决斗开始前报配置失败，关闭启动器创建的两个 GUI，保留清单与诊断 |
| 其他房间参数错误 | 决斗开始前报具体不符项，清单失败，保留 GUI |
| 单方投降或自然终局 | 两端均有结束事件与 `MSG_WIN` 且胜者一致才进入编译；结束后默认保留窗口，`--close-clients` 则关闭 |
| 单方终局、断线、提前关窗、主动取消、超时 | 在限定时间内结束等待，标记中止并报告双方最后事件；不生成已验证结果 |
| 一方已终局，另一方仍在录像保存弹窗 | 提示处理弹窗，暂停单方终局短宽限期，弹窗处理后重新计时；总录制时限继续生效 |
| 同形候选 | 自动记录序号和匹配数；一致时回放通过，不一致时定位步骤并要求审阅 |
| 日志接近及达到上限 | 接近时预警；达到时保留日志并标记不可验证 |
| 旧版 v1 JSONL | 仍可离线编译或得到明确诊断；历史分析草稿不会成为已验证回归 |
| 清单查询与删除 | 可查名称、ID、状态与大小；异常中断不显示成功；只能显式指定 ID 删除 |

2026-10-07 自动验证：`tests/test_record_duel_launcher.py` 用两个模拟客户端进程实测了未勾选“不洗牌”时 `config_failed`、清单落盘及只关闭启动器创建的两个进程；另测连接关闭后标记 `aborted`，以及录像保存弹窗待处理时宽限期重新计时的状态逻辑。`tools/duel-recordings.py list` 和 `latest` 对既有录制可读。删除命令仅检查了代码路径，未删除用户录制。

同日使用 `out/duel-recordings/8ed56016e03248fd8e0f1807e025fab1/draft/scenario.yaml` 完整运行无头双客户端并同步录制到 `out/recording-smoke-20261007/`；回放报告为 `out/agent-e2e-runs/1791307980-1117/scenario-report.json`，Host 获胜。新录制的 Host 提示/响应 136/136、自动空连锁 84；Guest 128/128、自动空连锁 99；双方均有终局，无录制器错误、连接异常或截断。新日志不依赖 `overrides.json` 即编译成功，自动序号使用 10 处，Host 135 步、Guest 126 步；生成的 YAML 与刚通过回放的原剧本逐字节一致。普通 GUI 人工录制的新 `manifest.json` 生命周期、窗口保留和无洗牌配置失败后的实际窗口关闭仍待人工目视验收；Windows 未验证。

通过验证的剧本仍由用户手动选择并放入 `tests/scenarios/`。Windows 与纯人工键鼠路径分别记录实测状态。

## 当前验证记录

2026-10-06：用无界面双客户端完整运行 `duel-001` 并启用同一客户端录制钩子，录得 Host 79 次提示/79 次响应、Guest 51 次提示/50 次响应（Guest 末次提示被 Host 投降终止），双方都有权威终局。8 处重复卡候选经记录核对后给出序号覆盖；生成 77 个 Host 步骤、49 个 Guest 步骤，其中 54/37 步含区域断言，终局双方各有 11 个区域断言。加强断言后的场景在另一轮无界面双客户端中复跑至 Guest 获胜，报告位于 `out/agent-e2e-runs/1791271059-45451/scenario-report.json`。此验证覆盖录制、编译、重放的核心路径；纯人工鼠标/键盘操作与 Windows 尚未实测。

同日使用 `surrender-smoke` 启动两台带窗口客户端并启用录制，双方记录到房间参数和权威终局；录制编译成功，生成场景再次通过无界面回归（`out/agent-e2e-runs/1791288697-72702/scenario-report.json`）。该轮由脚本驱动 GUI 客户端，尚不等同于人工键鼠录制验收。测试窗口已关闭。

用户随后手动完成录制 `783bd89c91554eebbc982a15f8987c12`。双端记录完整，Guest 投降，Host 获胜；人工 GUI 录制路径由此得到实测。房间启用了洗牌及卡组检查，实际起手与提交 YDK 前五张不同，并发生两次掷骰。严格编译正确拒绝回归；使用 `--analysis-draft` 提取了 Host 82 步、Guest 191 步的 `scenario.unverified.yaml`、中文时间线及诊断，未运行确定性回归。详见该录制目录的 `draft/analysis.md`。Windows 仍未验证。

第二次人工录制 `8ed56016e03248fd8e0f1807e025fab1` 启用了“不洗牌”，并自然结束于 Host 获胜。旧录制器在空连锁响应时出现一次错配，已从每条决策入站帧和对应出站响应重建双端独立副本，原始日志保留；修复详情见该目录 `repaired/repair-report.json`。生成的场景含 Host 135 步、Guest 126 步，在无界面双客户端复盘中全部完成，双方权威胜者及终局可见状态均匹配。报告：`out/agent-e2e-runs/1791304956-47995/scenario-report.json`。录制器已修复该错配路径；带 GUI 的剧本播放和 Windows 仍未验证。

用户选定该录制后，将已验证编译稿及双端 YDK 放入 `tests/scenarios/duel-002/`。v2 客户端把旧稿 30 处模糊的魔陷表示恢复为精确的 28 处正面、2 处里侧断言；最终入库文件再次经双客户端回放通过，见 `out/agent-e2e-runs/1791348511-48911/scenario-report.json`。该长剧本当前需 `--timeout 300`，命令见场景目录 README。

修复录制器后对同一剧本再次完整无界面回归并同步录制；Host 136/136、Guest 128/128 个提示/响应配对，双方无录制器错误且均确认 Host 获胜。第二次报告：`out/agent-e2e-runs/1791305173-51638/scenario-report.json`。带 GUI 的剧本播放和 Windows 仍未验证。
