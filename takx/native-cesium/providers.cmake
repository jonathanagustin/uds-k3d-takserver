# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# Include before add_subdirectory(patched-cesium). This is an actual imported
# SQLCipher archive with its real SQLite API, not a stock SQLite version alias.
if(NOT PUBLIC_SQLCIPHER_PREFIX OR NOT OPENSSL_ROOT_DIR)
  message(FATAL_ERROR "Explicit verified SQLCipher/OpenSSL prefixes required")
endif()
find_package(OpenSSL REQUIRED)
foreach(component Crypto SSL)
  get_target_property(provider OpenSSL::${component} IMPORTED_LOCATION)
  file(REAL_PATH "${provider}" actual)
  file(REAL_PATH "${OPENSSL_ROOT_DIR}" expected)
  string(FIND "${actual}" "${expected}/" position)
  if(NOT position EQUAL 0)
    message(FATAL_ERROR "OpenSSL provider escaped verified prefix")
  endif()
endforeach()
if(NOT TARGET SQLCipher::SQLCipher)
  if(NOT EXISTS "${PUBLIC_SQLCIPHER_PREFIX}/lib/libsqlite3.a" OR NOT EXISTS "${PUBLIC_SQLCIPHER_PREFIX}/include/sqlite3.h")
    message(FATAL_ERROR "Actual SQLCipher product missing")
  endif()
  add_library(SQLCipher::SQLCipher STATIC IMPORTED GLOBAL)
  set_target_properties(SQLCipher::SQLCipher PROPERTIES
    IMPORTED_LOCATION "${PUBLIC_SQLCIPHER_PREFIX}/lib/libsqlite3.a"
    INTERFACE_INCLUDE_DIRECTORIES "${PUBLIC_SQLCIPHER_PREFIX}/include"
    INTERFACE_LINK_LIBRARIES "OpenSSL::Crypto;${CMAKE_DL_LIBS};m")
endif()
