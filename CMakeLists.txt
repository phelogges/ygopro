cmake_minimum_required(VERSION 3.20.0)
project(ygopro LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)

if(MSVC)
    # Use static CRT to match vcpkg x64-windows-static builds
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "MSVC runtime library" FORCE)
endif()

# enable for clangd lsp
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Libevent CONFIG REQUIRED)
find_package(Freetype REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(unofficial-sqlite3 CONFIG REQUIRED)
find_package(Lua REQUIRED)
find_package(JPEG REQUIRED MODULE)
find_package(ZLIB REQUIRED)
find_package(PNG REQUIRED)
find_package(spdlog REQUIRED)
find_package(liblzma CONFIG REQUIRED)

if(CMAKE_SYSTEM_NAME MATCHES "Linux")
    add_compile_definitions(LUA_USE_LINUX)

elseif(APPLE)
    add_compile_definitions(LUA_USE_MACOSX)
    
elseif(CMAKE_SYSTEM_NAME MATCHES "BSD")
    add_compile_definitions(LUA_USE_POSIX)
endif()

# ocgcore target
file(GLOB OCGCORE_SOURCES "ocgcore/*.h" "ocgcore/*.cpp")
add_library(ocgcore STATIC ${OCGCORE_SOURCES})
target_include_directories(ocgcore PRIVATE ${LUA_INCLUDE_DIR})
target_link_libraries(ocgcore PRIVATE ${LUA_LIBRARIES})
target_include_directories(ocgcore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/ocgcore)

add_subdirectory(third_party)
# add_subdirectory(ocgcore)
add_subdirectory(gframe)

include(CTest)
if(BUILD_TESTING)
    add_executable(agent_codec_test tests/agent_codec_test.cpp gframe/agent_client/decision_codec.cpp)
    target_include_directories(agent_codec_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/gframe)
    target_link_libraries(agent_codec_test PRIVATE nlohmann_json::nlohmann_json)
    add_test(NAME agent_codec COMMAND agent_codec_test)
    find_package(Python3 3.12 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(NAME agent_codec_sdk_contract
            COMMAND ${CMAKE_COMMAND} -E env
                "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/agent_sdk/src"
                ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_codec_sdk.py
                $<TARGET_FILE:agent_codec_test>)
    endif()
endif()
