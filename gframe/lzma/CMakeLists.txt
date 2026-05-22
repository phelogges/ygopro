project (clzma)

file(GLOB SRC_FILES "*.h" "*.c")

add_library(${PROJECT_NAME} STATIC ${SRC_FILES})
