cmake_minimum_required(VERSION 3.20.0)
project(ygopro LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)

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

