# Windows Debug 构建验证（2026-10-21）

> 状态：历史验证记录；截至 2026-10-21 的 `fix/windows-debug-build` 分支本机结果。现行入口见[验证总览](README.md)。

## 环境与路径

- Windows x64，Visual Studio 2026 / MSVC 19.50.35722.0，CMake 4.3.4，vcpkg `x64-windows-static`。
- 项目入口：`cmake --preset VS2026-x64-Debug`。
- 构建入口：`cmake --build --preset VS2026-x64-Debug`。
- 测试入口：`ctest --test-dir out/build/VS2026-x64-Debug -C Debug --output-on-failure`。

## 结果

- 配置和完整 Debug 构建通过，生成 `out/build/VS2026-x64-Debug/gframe/Debug/ygopro.exe`、`agent_codec_test.exe` 和 `agent_response_decode.exe`。
- CTest 3/3 通过：`agent_codec`、`agent_codec_sdk_contract`、`agent_message_coverage`。CTest 使用本机 Python 3.13.11。
- 初次构建的失败点是测试目标缺少 MSVC `/utf-8`、Windows socket 无效值的列表初始化窄化转换，以及强制 `mainCRTStartup` 与实际 `wWinMain` 不匹配。修复后均通过。
- 初次 CTest 的两个失败点是 Python 按 Windows 默认 GBK 解码 UTF-8 子进程输出和 JSON 清单。显式使用 UTF-8 后通过。

## 未验证

- macOS 对本分支改动的构建与测试；Windows GUI 启动、双客户端对局、真实模型与超时或断线接管。
