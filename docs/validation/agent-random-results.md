# 硬币与骰子公开结果事件验证

> 状态：历史验证记录；截至原测试记录（原页未注明日期）。现行验证范围见[验证总览](README.md)。

## 问题与修复

一次人工对局中，对手发动卡片 `40235813` 后，客户端收到 `MSG_TOSS_COIN`（130）报文 `82 01 01 00`：对手投掷一次，GUI 显示结果为反面。Agent 事件解析器原先没有处理该消息，因而记录 `event_decode_incomplete`，后续决策返回 `history_incomplete`。对手此前公开宣布的 `HINT_OPSELECTED` 选项值 `61` 已作为原始提示事件记录。

客户端现将公开的硬币／骰子结果分别记录为 `coin_tossed`／`dice_rolled`，并为公开选出的正反面选项补充语义值。字段和异常处理见 [HTTP v2 观测事件契约](../contracts/agent-http-v2.md#观测事件)。解析器不推断卡片效果是否成功。

## 已执行验证

- macOS Debug：`cmake --build --preset MacOS-Debug --target agent_codec_test ygopro` 通过。
- `ctest --test-dir out/build/MacOS-Debug --output-on-failure -R '^agent_codec$'` 通过；覆盖捕获到的硬币消息、多个骰子结果、截断、尾部多余字节及非法值。
- `agent_sdk/.venv/bin/python -m unittest discover -s tests -q`：84 项通过，包括事件持久接收与非法结果拒绝。
- `agent_sdk/.venv/bin/ruff check src/agent_sdk/state.py tests/test_state.py` 通过；`agent_sdk/.venv/bin/pyright src/agent_sdk/state.py` 为零错误。
- `agent_server/.venv/bin/python -m unittest discover -s tests -p test_http_service.py -q`：5 项通过。此项测试需要本地回环套接字，已在允许套接字的环境运行。
- `python3.12 tools/agent-e2e.py --games 3 --deck deck/test/test.ydk`：三局均由双方客户端记录正常终局，脚本退出码为 `0`。本次三局未触发硬币或骰子结果，随机结果的覆盖来自上面的捕获报文测试。

`ruff format --check` 对 `agent_sdk/src/agent_sdk/state.py` 仍报告原有格式差异；用提交基线文件复核得到同样结果。本次新增的解析逻辑没有引入该差异。

## 尚未验证

修复后的真实双客户端 GUI 新局尚未运行，因此未确认模型在包含该随机结果的后续决策中的实际表现。此前被标记为历史不完整的对局无法通过重试恢复漏掉的事件，须在新局验证。
