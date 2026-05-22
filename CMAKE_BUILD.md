# CMake Build

Use `CMake` as build tool, `vcpkg` as package manager.

## `vcpkg`

Install [`vcpkg`](https://learn.microsoft.com/en-us/vcpkg/get_started/get-started)

## `CMake`

We recommend using the VS Code CMake Tools extension for interactive builds, Check [CMake Tools Docs](https://github.com/microsoft/vscode-cmake-tools/blob/0bd2ab800914e892768458a10bb459483764eaef/docs/cmake-presets.md) for more details.

In terminal mode:
```shell
# Check available presets
$ cmake --list-presets
# Available configure presets:

#  "MacOS-Debug"          - Clang 15.0.0 x86_64-apple-darwin25.2.0 Debug
#  "MacOS-RelWithDebInfo" - Clang 15.0.0 x86_64-apple-darwin25.2.0 RelWithDebInfo

# Choose one preset to configurate, this will call vcpkg install packages
$ cmake --preset MacOS-Debug

# After configuration finished, build this preset
$ cmake --build --preset MacOS-Debug
```

After building finished, building could be found in `out/build` directory, check `CMakePresets.json` for more details.