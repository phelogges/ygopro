project(cspmemvfs)

add_library(${PROJECT_NAME} STATIC
    spmemvfs.h spmemvfs.c
)

if(NOT MSVC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE _POSIX_C_SOURCE=200809L)
endif()

target_link_libraries(${PROJECT_NAME} PRIVATE unofficial::sqlite3::sqlite3)