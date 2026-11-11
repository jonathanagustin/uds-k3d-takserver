# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
cmake_minimum_required(VERSION 3.24)
project(PublicKernelNative LANGUAGES C CXX)
set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_FIND_USE_PACKAGE_REGISTRY OFF)
set(CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY OFF)

# Explicit validated producer roots only; no package acquisition or host fallback.
foreach(input CESIUM_OUTPUT CESIUM_SOURCE CESIUM_RECIPE KERNEL_LAYOUT JNI_HEADERS GDAL_JNI GDAL_INSTALL MINIZIP GLES
              SPATIAL GEOS PROJ SQLCIPHER ASSIMP LAS MDB DRACO GLTF GLTFLOADER KML GLES_EXTRA CURL_ROOT)
  if(NOT IS_DIRECTORY "${${input}}")
    message(FATAL_ERROR "Missing real prerequisite ${input}")
  endif()
endforeach()
set(CESIUM_PUBLIC_PREFIX "${CESIUM_OUTPUT}/install")
set(PUBLIC_SQLCIPHER_PREFIX "${SQLCIPHER}/sqlcipher-install")
set(OPENSSL_ROOT_DIR "${SQLCIPHER}/openssl-install")
set(OPENSSL_USE_STATIC_LIBS TRUE)
set(CMAKE_PREFIX_PATH "${CESIUM_PUBLIC_PREFIX};${OPENSSL_ROOT_DIR};${DRACO}/install")
set(CMAKE_FIND_ROOT_PATH "${CESIUM_PUBLIC_PREFIX};${OPENSSL_ROOT_DIR};${DRACO}/install;$ENV{JAVA_HOME}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
list(APPEND CMAKE_PREFIX_PATH "${CURL_ROOT}/install" "${ASSIMP}/zlib-install")
list(APPEND CMAKE_FIND_ROOT_PATH "${CURL_ROOT}/install" "${ASSIMP}/zlib-install")
set(ZLIB_ROOT "${ASSIMP}/zlib-install")
set(ZLIB_LIBRARY "${ASSIMP}/zlib-install/lib/libz.a" CACHE FILEPATH "Verified source-built zlib" FORCE)
set(ZLIB_INCLUDE_DIR "${ASSIMP}/zlib-install/include" CACHE PATH "Verified source-built zlib headers" FORCE)
set(ZLIB_USE_STATIC_LIBS TRUE)
set(VCPKG_MANIFEST_MODE ON CACHE BOOL "" FORCE)
set(VCPKG_MANIFEST_INSTALL OFF CACHE BOOL "" FORCE)
set(CESIUM_TESTS_ENABLED OFF CACHE BOOL "" FORCE)
set(CESIUM_GLM_STRICT_ENABLED ON CACHE BOOL "" FORCE)
set(CESIUM_INSTALL_STATIC_LIBS OFF CACHE BOOL "" FORCE)
set(CESIUM_INSTALL_HEADERS OFF CACHE BOOL "" FORCE)
include("${CESIUM_RECIPE}/providers.cmake")
find_package(draco CONFIG REQUIRED PATHS "${DRACO}/install" NO_DEFAULT_PATH)
find_package(spdlog CONFIG REQUIRED PATHS "${CESIUM_PUBLIC_PREFIX}" NO_DEFAULT_PATH)
find_package(s2 CONFIG REQUIRED PATHS "${CESIUM_PUBLIC_PREFIX}" NO_DEFAULT_PATH)
find_package(uriparser CONFIG REQUIRED PATHS "${CESIUM_PUBLIC_PREFIX}" NO_DEFAULT_PATH)
find_package(CURL CONFIG REQUIRED PATHS "${CURL_ROOT}/install" NO_DEFAULT_PATH)
add_subdirectory("${CESIUM_SOURCE}" cesium)
set(cesium_targets
  CesiumUtility CesiumGltf CesiumGeometry CesiumGeospatial CesiumJsonReader
  CesiumJsonWriter CesiumGltfContent CesiumGltfReader CesiumGltfWriter CesiumAsync
  Cesium3DTiles Cesium3DTilesReader Cesium3DTilesWriter Cesium3DTilesContent
  CesiumRasterOverlays Cesium3DTilesSelection CesiumIonClient CesiumQuantizedMeshTerrain)
foreach(real_target IN LISTS cesium_targets)
  if(NOT TARGET "${real_target}")
    message(FATAL_ERROR "Missing genuine Cesium target ${real_target}")
  endif()
endforeach()

function(real_library target kind path)
  if(NOT EXISTS "${path}")
    message(FATAL_ERROR "Missing actual library ${path}")
  endif()
  add_library("${target}" ${kind} IMPORTED GLOBAL)
  set_property(TARGET "${target}" PROPERTY IMPORTED_LOCATION "${path}")
endfunction()
real_library(UDS::GLES SHARED "${GLES}/install/lib/libGLESv2.so.2.1.0")
real_library(UDS::GDAL SHARED "${GDAL_JNI}/lib/libgdal.so")
real_library(UDS::Spatialite STATIC "${SPATIAL}/libspatialite-install/lib/libspatialite.a")
real_library(UDS::GEOS_C STATIC "${GEOS}/install/lib/libgeos_c.a")
real_library(UDS::GEOS STATIC "${GEOS}/install/lib/libgeos.a")
real_library(UDS::PROJ STATIC "${PROJ}/install/lib/libproj.a")
real_library(UDS::XML STATIC "${SPATIAL}/libxml2-install/lib/libxml2.a")
real_library(UDS::Iconv STATIC "${SPATIAL}/libiconv-install/lib/libiconv.a")
real_library(UDS::Zlib STATIC "${ASSIMP}/zlib-install/lib/libz.a")
real_library(UDS::Assimp SHARED "${ASSIMP}/install/lib/libassimp.so.4.1.0")
real_library(UDS::LAS SHARED "${LAS}/install/lib/liblas.so.2.4.0")
real_library(UDS::LAS_C SHARED "${LAS}/install/lib/liblas_c.so.2.4.0")
real_library(UDS::MDB STATIC "${MDB}/install/lib/libmdb.a")
real_library(UDS::Minizip STATIC "${MINIZIP}/libminizip.a")
real_library(UDS::Expat STATIC "${KML}/expat-install/lib/libexpat.a")
foreach(family base dom engine convenience regionator xsd)
  real_library("UDS::KML_${family}" STATIC "${KML}/install/lib/libkml${family}.a")
endforeach()
set_property(TARGET UDS::KML_base PROPERTY INTERFACE_LINK_LIBRARIES "UDS::Expat;UDS::Minizip;UDS::Zlib;uriparser::uriparser")
set_property(TARGET UDS::KML_dom PROPERTY INTERFACE_LINK_LIBRARIES "UDS::KML_base")
set_property(TARGET UDS::KML_engine PROPERTY INTERFACE_LINK_LIBRARIES "UDS::KML_dom;UDS::KML_base")
set_property(TARGET UDS::KML_convenience PROPERTY INTERFACE_LINK_LIBRARIES "UDS::KML_engine;UDS::KML_dom;UDS::KML_base")
set_property(TARGET UDS::KML_regionator PROPERTY INTERFACE_LINK_LIBRARIES "UDS::KML_convenience;UDS::KML_engine;UDS::KML_dom;UDS::KML_base")
set_property(TARGET UDS::KML_xsd PROPERTY INTERFACE_LINK_LIBRARIES "UDS::KML_base")
set_property(TARGET UDS::Spatialite PROPERTY INTERFACE_LINK_LIBRARIES
  "UDS::GEOS_C;UDS::GEOS;UDS::PROJ;UDS::XML;UDS::Iconv;UDS::Zlib;SQLCipher::SQLCipher")

# Keep both complete official targets and platform compile definitions/options.
# Only dependency locations/target graph replace credentialed Conan and the
# upstream manually ordered Cesium archives. No source list is reduced.
set(khronos_INCLUDE_DIRS "${GLES}/include")
set(tinygltf-tak_INCLUDE_DIRS "${GLTF}")
set(tinygltfloader-tak_INCLUDE_DIRS "${GLTFLOADER}")
set(ttp-dist_INCLUDE_DIRS
  "${SQLCIPHER}/sqlcipher-install/include" "${SPATIAL}/libspatialite-install/include"
  "${GDAL_INSTALL}/include"
  "${GDAL_JNI}/source-reference/gdal/gdal/port" "${GDAL_JNI}/source-reference/gdal/gdal/gcore"
  "${GDAL_JNI}/source-reference/gdal/gdal/ogr" "${GDAL_JNI}/source-reference/gdal/gdal/alg"
  "${GDAL_JNI}/source-reference/gdal/gdal/apps" "${GDAL_JNI}/source-reference/gdal/gdal/gnm"
  "${GDAL_JNI}/source-reference/libkml/libkml-1.3/third_party/zlib-1.2.3/contrib"
  "${GEOS}/install/include" "${PROJ}/install/include" "${MDB}/install/include"
  "${KML}/install/include" "${KML}/expat-install/include"
  "${SPATIAL}/libxml2-install/include/libxml2" "${SPATIAL}/libiconv-install/include"
  "${ASSIMP}/install/include" "${ASSIMP}/zlib-install/include")
set(libLAS_INCLUDE_DIRS "${LAS}/install/include" "${LAS}/source/libLAS/find_package/boost")
set(draco_INCLUDE_DIRS "${DRACO}/install/include")
set(cesium-native_INCLUDE_DIRS "${CESIUM_PUBLIC_PREFIX}/include")
set(kernel_root "${KERNEL_LAYOUT}/takkernel/engine")
add_subdirectory("${kernel_root}/src/main/cpp" kernel-cpp)
add_subdirectory("${kernel_root}/src/main/jni" kernel-jni)
# The unchanged CPU GLU tessellator includes genuine ES1 type declarations.
# Scope this header root to its C sources; no ES1 rendering API is substituted.
get_target_property(kernel_sources takengine SOURCES)
foreach(source IN LISTS kernel_sources)
  if(source MATCHES "formats/glues/.*\\.c$")
    if(NOT IS_ABSOLUTE "${source}")
      set(source "${kernel_root}/src/main/cpp/${source}")
    endif()
    set_source_files_properties("${source}" TARGET_DIRECTORY takengine PROPERTIES INCLUDE_DIRECTORIES "${GLES_EXTRA}")
  endif()
endforeach()
set_source_files_properties("${kernel_root}/src/main/cpp/util/URIOfflineCache.cpp"
  TARGET_DIRECTORY takengine PROPERTIES
  INCLUDE_DIRECTORIES "$<TARGET_PROPERTY:CURL::libcurl_static,INTERFACE_INCLUDE_DIRECTORIES>"
  COMPILE_DEFINITIONS "$<TARGET_PROPERTY:CURL::libcurl_static,INTERFACE_COMPILE_DEFINITIONS>")
set(real_dependencies
  UDS::GLES UDS::GDAL UDS::Spatialite UDS::MDB UDS::Assimp UDS::LAS UDS::LAS_C UDS::Minizip UDS::Zlib
  UDS::KML_regionator UDS::KML_convenience UDS::KML_engine UDS::KML_dom UDS::KML_xsd UDS::KML_base
  "$<LINK_ONLY:CURL::libcurl_static>"
  SQLCipher::SQLCipher draco::draco spdlog::spdlog s2::s2 ${cesium_targets} ${CMAKE_DL_LIBS} pthread m rt)
set_property(TARGET takengine PROPERTY LINK_DIRECTORIES "")
set_property(TARGET takengine PROPERTY LINK_LIBRARIES "${real_dependencies}")
set_property(TARGET takenginejni PROPERTY LINK_DIRECTORIES "")
set_property(TARGET takenginejni PROPERTY LINK_LIBRARIES "takengine;UDS::GLES;UDS::GDAL;UDS::Spatialite;SQLCipher::SQLCipher;draco::draco;Cesium3DTilesSelection")
target_include_directories(takenginejni PRIVATE "${JNI_HEADERS}")
foreach(target takengine takenginejni)
  target_link_options(${target} PRIVATE "-Wl,--no-undefined" "-Wl,--exclude-libs,libssl.a:libcrypto.a:libexpat.a")
endforeach()

# Core is the shared SQLCipher owner; do not exclude its SQLite archive.
# Core remains the unique public SQLCipher owner for JNI's two real imports.
target_link_options(takengine PRIVATE
  "-Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/core-sqlcipher.map")
set_property(TARGET takengine APPEND PROPERTY LINK_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/core-sqlcipher.map")
