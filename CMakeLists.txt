cmake_minimum_required(VERSION 3.20.0)
project(ygopro LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)

find_package(Libevent CONFIG REQUIRED)
find_package(Freetype REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(unofficial-sqlite3 CONFIG REQUIRED)
find_package(Lua REQUIRED)

if(CMAKE_SYSTEM_NAME MATCHES "Linux")
    add_compile_definitions(LUA_USE_LINUX)

elseif(APPLE)
    add_compile_definitions(LUA_USE_MACOSX)
    
elseif(CMAKE_SYSTEM_NAME MATCHES "BSD")
    add_compile_definitions(LUA_USE_POSIX)
endif()

option(ENABLE_AUDIO "Use miniaudio for audio playback" ON)
if (ENABLE_AUDIO)
    add_compile_definitions(YGOPRO_USE_MINIAUDIO)

    file(GLOB MINIAUDIO_SRC
        "third_party/miniaudio/extras/miniaudio_split/miniaudio.h"
        "third_party/miniaudio/extras/miniaudio_split/miniaudio.c"
    )

    add_library(miniaudio STATIC ${MINIAUDIO_SRC})
    target_compile_definitions(miniaudio PRIVATE 
        MA_NO_ENCODING 
        MA_NO_GENERATION 
        MA_NO_NEON
    )
endif()

add_subdirectory(third_party/irrlicht)
add_subdirectory(ocgcore)
add_subdirectory(gframe)

