project (ygopro)

add_subdirectory(lzma)
add_subdirectory(spmemvfs)

file(GLOB SRC_FILES "*.h" "*.cpp")

add_executable(${PROJECT_NAME} WIN32 ${SRC_FILES})

if (MSVC)
    # disable RTTI
    target_compile_options(${PROJECT_NAME} PRIVATE /GR-)
    target_compile_definitions(${PROJECT_NAME} PRIVATE _IRR_WCHAR_FILESYSTEM)
    target_link_options(${PROJECT_NAME} PRIVATE /ENTRY:mainCRTStartup)

    target_sources(${PROJECT_NAME} PRIVATE "resource/gframe/ygopro.rc")

    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 iphlpapi)

    find_package(OpenMP REQUIRED)
    target_link_libraries(${PROJECT_NAME} PRIVATE OpenMP::OpenMP_CXX)

elseif (UNIX AND NOT APPLE)
    target_link_libraries(${PROJECT_NAME} PRIVATE GL X11 Xxf86vm dl pthread)

    find_package(OpenMP REQUIRED)
    target_link_libraries(${PROJECT_NAME} PRIVATE OpenMP::OpenMP_CXX)

elseif (APPLE)
    target_compile_definitions(${PROJECT_NAME} PRIVATE GL_SILENCE_DEPRECATION)
    target_link_libraries(${PROJECT_NAME} PRIVATE 
        "-framework OpenGL"
        "-framework Cocoa"
        "-framework IOKit"
    )
    set(TARGET_ARCHS "")
    if(MAC_ARM)
        list(APPEND TARGET_ARCHS "arm64")
    endif()

    if(MAC_INTEL)
        list(APPEND TARGET_ARCHS "x86_64")
    endif()

    if(TARGET_ARCHS)
        set_target_properties(YGOPro PROPERTIES OSX_ARCHITECTURES "${TARGET_ARCHS}")
    endif()
    
else ()
    message(FATAL "Only Windows, Linux, MacOS supported")
endif()

target_include_directories(${PROJECT_NAME} PRIVATE ${LUA_INCLUDE_DIR})

target_link_libraries(${PROJECT_NAME} PRIVATE
    irrlicht
    ocgcore
    clzma
    cspmemvfs
    miniaudio
    ${LUA_LIBRARIES}                                                                                                                                                                                                                                   
    unofficial::sqlite3::sqlite3
    libevent::core libevent::extra libevent::pthreads
    Freetype::Freetype
)
