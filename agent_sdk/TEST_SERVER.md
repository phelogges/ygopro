# 确定性 HTTP 测试端

仅用于验证客户端完整请求、合法动作转换和 HTTP 生命周期。运行时只需要 Python 3.12 标准库，使用 SDK 的 `parse_request`、`translate_intent`、`build_response`。不会提供竞争级对局策略。

从仓库根目录启动，指定客户端实际使用的数据库：

```bash
uv run --project agent_sdk python -m agent_sdk.test_server --cards-db cards.cdb
```

默认监听 `127.0.0.1:8910`，接口为 `POST /v1/decision`，UTF-8 JSON。启动会读取文件内容计算 SHA-256，每次请求核对客户端指纹；不一致返回 HTTP 409 `database_mismatch`。数据库应在服务运行期间保持不变；更新后重启服务。

局域网监听需要显式启用并配置 token：

```bash
export YGOPRO_AGENT_TOKEN='your-shared-token'
uv run --project agent_sdk python -m agent_sdk.test_server \
  --cards-db cards.cdb --host 0.0.0.0 --allow-lan --port 8910
```

客户端配置同一个 token，发送 `Authorization: Bearer <token>`。可用 `--token-env NAME` 指定其他环境变量。未授权返回 401。传输为 HTTP，适用于可信本机/局域网测试。

策略先进行可完成的通常召唤/盖放，再推进战斗阶段；战斗时优先攻击，之后进入主要阶段二或结束回合。不会反复改变表示或自由发动效果。连锁优先放弃、可选效果优先拒绝；强制选择仍交由 SDK 校验。组合选择按输入顺序搜索首个合法解，处理必选素材、SUM、解放、区域、计数器及已解析的声明卡过滤；逐步选卡优先完成，再选卡，避免反复撤销。搜索最多尝试 8192 个组合；不支持的约束、没有安全策略或无法找到合法解返回 422 `unsupported_prompt`，保留人工入口。

请求和响应各限制 1 MiB，请求必须提供单个 `Content-Length`，不支持 chunked。正文读取超时为 10 秒；已过期决策返回 408。测试端采用单线程 `HTTPServer`，适合一期串行决策；不用于高并发服务。

运行专属测试：

```bash
uv run --project agent_sdk python -m unittest discover -s agent_sdk/tests -p test_test_server.py -v
```

测试包含实际 HTTP 请求，因此环境需要允许绑定本机临时端口。
