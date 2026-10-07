# Agent 服务 macOS 发行

本页记录二期发行包的目录契约和检查方法。当前脚本只构建 macOS；Windows 最后按相同的发布根目录布局实现与验证。发行物不含签名、公证或安装器。

## 构建

在项目根目录准备好 CMake + vcpkg、`uv`、Python 3.12，以及本地 `cards.cdb` 和客户端运行资源。`agent_server/uv.lock` 锁定 Python 依赖；构建脚本通过 `uv` 调用 PyInstaller，将服务打为发布根目录的 `agent-server` 单文件可执行程序。

```bash
python3.12 tools/agent-release.py check-inputs --preset MacOS-RelWithDebInfo
python3.12 tools/agent-release.py build --preset MacOS-RelWithDebInfo
```

`build` 先配置、编译 CMake preset，再构建 Python 服务，输出：

```text
out/release/ygopro-agent-macos-<版本>/
out/release/ygopro-agent-macos-<版本>.zip
```

已有同名目录或 zip 时脚本报错，避免覆盖发布物。需要重新构建时由操作者先移动或清理旧产物。也可用 `--output-dir` 指定其他输出目录。资源较大，尤其本地 `pics/`；打包时间和 zip 体积取决于本地卡图数量。

## 发布根目录

```text
ygopro-agent-macos-<版本>/
├── ygopro
├── agent-server
├── cards.cdb
├── strings.conf
├── lflist.conf
├── system.conf
├── script/ textures/ pics/ sound/ pack/
├── deck/ replay/ single/          # 空目录，不复制个人对局数据
└── .agents/
    ├── config.toml               # 从版本管理的 config.example.toml 复制
    ├── release-manifest.json
    └── skills/
        ├── ocg-rulebook/
        └── ygo-card-db/
```

存在时还会复制 `fonts/`、`icon/`、`expansions/`、`resource/`。`system.conf` 来自 Git 的 `HEAD` 版本，不取工作区中客户端运行后的值。技能只复制运行时参考文件和代码；不复制测试、缓存或技能目录中的旧卡库。整个发布根目录只有一份 `cards.cdb`，供客户端与卡片技能共用。`.agents/data/`、日志、API 密钥和个人牌组不会进入包。

发布后在 `.agents/config.toml` 中设置 Responses 端点与模型名，并通过配置指定的环境变量提供 API 密钥。两个客户端分别使用不同的固定端口配置档；从发布根目录启动客户端，以便相对资源路径和 `./agent-server` 路径正确解析。

## 验证与限制

```bash
python3.12 tools/agent-release.py verify out/release/ygopro-agent-macos-<版本>
```

验证检查可执行权限、必要目录、配置、SQLite 数据库结构与快速完整性、关键文件 SHA-256，以及禁止的本地数据路径。打包过程在临时目录中组装并验证，成功后再移动到最终位置。

此检查是发行物静态验证；真实模型端点、客户端 GUI 和双客户端决斗需另做运行验证。Windows 构建与验证尚未执行。
