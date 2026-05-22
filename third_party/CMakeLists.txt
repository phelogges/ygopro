cmake_minimum_required(VERSION 3.20.0)

# MacOS build reference
# https://github.com/microsoft/vcpkg/blob/2626652f01caffa87a42f354d6fc43552ebd8db2/ports/irrlicht/CMakeLists.txt

project(irrlicht LANGUAGES C CXX)


option(ENABLE_AUDIO "Use miniaudio for audio playback" ON)
if (ENABLE_AUDIO)
    add_compile_definitions(YGOPRO_USE_MINIAUDIO)

    file(GLOB MINIAUDIO_SRC
        "miniaudio/extras/miniaudio_split/miniaudio.h"
        "miniaudio/extras/miniaudio_split/miniaudio.c"
    )

    add_library(miniaudio STATIC ${MINIAUDIO_SRC})
    target_compile_definitions(miniaudio PRIVATE 
        MA_NO_ENCODING 
        MA_NO_GENERATION 
        MA_NO_NEON
        MA_NO_SSE2
        MA_NO_AVX2
    )
endif()


set(irrlicht_target_name irrlicht)

file (GLOB IRR_SRC_FILES
    "irrlicht/include/*h"
    "irrlicht/source/Irrlicht/*.cpp"
)

if (APPLE)
    file(GLOB IRR_SRC_FILES_MACOS "irrlicht/source/Irrlicht/*.mm")
    set(IRR_SRC_FILES ${IRR_SRC_FILES} ${IRR_SRC_FILES_MACOS})
endif()

add_library(${irrlicht_target_name} STATIC ${IRR_SRC_FILES})

target_link_libraries(${irrlicht_target_name} PRIVATE
    JPEG::JPEG
    PNG::PNG
    ZLIB::ZLIB
)

target_include_directories(${irrlicht_target_name}
    PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/irrlicht/include"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/irrlicht/source/Irrlicht"
)

target_compile_definitions(${irrlicht_target_name} PUBLIC
    "_IRR_STATIC_LIB_"
    "NO_IRR_USE_NON_SYSTEM_JPEG_LIB_"
    "NO_IRR_USE_NON_SYSTEM_LIB_PNG_"
    "NO_IRR_USE_NON_SYSTEM_ZLIB_"
    "NO_IRR_LINUX_X11_VIDMODE_"
    "NO_IRR_COMPILE_WITH_BZIP2_"
    "NO_IRR_COMPILE_WITH_LZMA_"
    "NO_IRR_COMPILE_WITH_CONSOLE_DEVICE_"
    "NO_IRR_COMPILE_WITH_DIRECT3D_8_"
    "NO_IRR_COMPILE_WITH_DIRECTINPUT_JOYSTICK_"
    "NO_IRR_COMPILE_WITH_JOYSTICK_EVENTS_"
    "NO_IRR_COMPILE_WITH_SOFTWARE_"
    "NO_IRR_COMPILE_WITH_BURNINGSVIDEO_"
    "NO_IRR_COMPILE_WITH_IRR_SCENE_LOADER_"
    "NO_IRR_COMPILE_WITH_SKINNED_MESH_SUPPORT_"
    "NO_IRR_COMPILE_WITH_IRR_MESH_LOADER_"
    "NO_IRR_COMPILE_WITH_HALFLIFE_LOADER_"
    "NO_IRR_COMPILE_WITH_MD2_LOADER_"
    "NO_IRR_COMPILE_WITH_MD3_LOADER_"
    "NO_IRR_COMPILE_WITH_3DS_LOADER_"
    "NO_IRR_COMPILE_WITH_COLLADA_LOADER_"
    "NO_IRR_COMPILE_WITH_CSM_LOADER_"
    "NO_IRR_COMPILE_WITH_BSP_LOADER_"
    "NO_IRR_COMPILE_WITH_DMF_LOADER_"
    "NO_IRR_COMPILE_WITH_LMTS_LOADER_"
    "NO_IRR_COMPILE_WITH_MY3D_LOADER_"
    "NO_IRR_COMPILE_WITH_OBJ_LOADER_"
    "NO_IRR_COMPILE_WITH_OCT_LOADER_"
    "NO_IRR_COMPILE_WITH_LWO_LOADER_"
    "NO_IRR_COMPILE_WITH_STL_LOADER_"
    "NO_IRR_COMPILE_WITH_PLY_LOADER_"
    "NO_IRR_COMPILE_WITH_SMF_LOADER_"
    "NO_IRR_COMPILE_WITH_IRR_WRITER_"
    "NO_IRR_COMPILE_WITH_COLLADA_WRITER_"
    "NO_IRR_COMPILE_WITH_STL_WRITER_"
    "NO_IRR_COMPILE_WITH_OBJ_WRITER_"
    "NO_IRR_COMPILE_WITH_PLY_WRITER_"
    "NO_IRR_COMPILE_WITH_PCX_LOADER_"
    "NO_IRR_COMPILE_WITH_PPM_LOADER_"
    "NO_IRR_COMPILE_WITH_PSD_LOADER_"
    "NO_IRR_COMPILE_WITH_PVR_LOADER_"
    "NO_IRR_COMPILE_WITH_DDS_LOADER_"
    "NO_IRR_COMPILE_WITH_TGA_LOADER_"
    "NO_IRR_COMPILE_WITH_WAL_LOADER_"
    "NO_IRR_COMPILE_WITH_LMP_LOADER_"
    "NO_IRR_COMPILE_WITH_RGB_LOADER_"
    "NO_IRR_COMPILE_WITH_PCX_WRITER_"
    "NO_IRR_COMPILE_WITH_PPM_WRITER_"
    "NO_IRR_COMPILE_WITH_PSD_WRITER_"
    "NO_IRR_COMPILE_WITH_TGA_WRITER_"
    "NO__IRR_COMPILE_WITH_PAK_ARCHIVE_LOADER_"
    "NO__IRR_COMPILE_WITH_NPK_ARCHIVE_LOADER_"
    "NO__IRR_COMPILE_WITH_WAD_ARCHIVE_LOADER_"
    "NO_IRR_COMPILE_WITH_ZIP_ENCRYPTION_"
)

if(MSVC)
    target_compile_options(${irrlicht_target_name} PRIVATE
        /GR-           
        /EHs-c-        
        /D_HAS_EXCEPTIONS=0 
    )
    target_compile_definitions(${irrlicht_target_name} PRIVATE 
        UNICODE
        _UNICODE
        _IRR_WCHAR_FILESYSTEM
        NO_IRR_COMPILE_WITH_DIRECT3D_9_
        NO_IRR_COMPILE_WITH_JOYSTICK_EVENTS_
    )
else()
    target_compile_options(${irrlicht_target_name} PRIVATE    
        -fno-rtti
        -fno-exceptions 
    )
    if (APPLE)
        target_compile_definitions(${irrlicht_target_name} PRIVATE GL_SILENCE_DEPRECATION)
        # target_include_directories(${irrlicht_target_name} PRIVATE source/Irrlicht/MacOSX)
        target_compile_definitions(${irrlicht_target_name} PRIVATE SYSTEM=MacOSX)

        target_link_libraries(${irrlicht_target_name} ${OSX_LIBRARIES})

        target_compile_options(${irrlicht_target_name} PRIVATE "-ObjC++")

        set(ADDITIONAL_LIRARIES
            "-framework OpenGL"
            "-framework IOKit"
            "-framework Carbon"
            "-framework AppKit"
            "-framework Cocoa")
        target_link_libraries(${irrlicht_target_name} PRIVATE ${ADDITIONAL_LIRARIES})
    else ()
        target_compile_definitions(${irrlicht_target_name} PRIVATE "NO_IRR_COMPILE_WITH_JOYSTICK_EVENTS_")
    endif ()
endif()