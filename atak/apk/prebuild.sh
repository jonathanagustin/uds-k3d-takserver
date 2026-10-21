#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Builds the native dependencies of ATAK-CIV for one Android ABI and publishes
# them to the local conan cache and maven local. The upstream tree carries the
# sources; the conan recipes it lacks (khronos, draco, tinygltf, cesium-native)
# live next to this script.
#
# Usage: prebuild.sh [phase ...]   (no phase = all, in order)
set -euo pipefail

SRC=${SRC:-/src/atak-civ}
RECIPES=${RECIPES:-$(cd "$(dirname "$0")" && pwd)/conan}
ABI=${ABI:-x86_64}
JOBS=${JOBS:-$(nproc)}
CESIUM_REF=${CESIUM_REF:-v0.40.1}

case "${ABI}" in
  x86_64) CARCH=x86_64 ;;
  x86) CARCH=x86 ;;
  arm64-v8a) CARCH=armv8 ;;
  armeabi-v7a) CARCH=armv7 ;;
  *) echo "unknown ABI ${ABI}" >&2; exit 2 ;;
esac
CONAN_S=(-s "arch=${CARCH}" -s os=Android -s os.api_level=21 -s compiler=gcc
  -s compiler.version=8 -s compiler.libcxx=libstdc++ -s build_type=Release)
NDK_CMAKE=(-G Ninja "-DCMAKE_TOOLCHAIN_FILE=${ANDROID_NDK}/build/cmake/android.toolchain.cmake"
  -DCMAKE_BUILD_TYPE=Release "-DANDROID_ABI=${ABI}" -DANDROID_PLATFORM=android-21)

log() { printf '=== %s %s\n' "$(date -u +%H:%M:%S)" "$*"; }

extract() {
  cd "${SRC}"
  tar xzf depends/assimp-4.0.1-mod.tar.gz -C .
  tar xzf depends/gdal-2.4.4-mod.tar.gz -C .
  tar xzf depends/libLAS-1.8.2-mod.tar.gz -C .
  tar xzf depends/LASzip-3.4.3-mod.tar.gz -C .
  tar xzf depends/tinygltf-2.4.1-mod.tar.gz -C takengine/thirdparty
}

ttp() {
  cd "${SRC}"
  make -C takthirdparty "TARGET=android-${ABI}" GDAL_USE_KDU=no \
    build_spatialite build_commoncommo build_gdal build_assimp
}

conan_profile() {
  conan profile new default --detect >/dev/null 2>&1 || true
  conan profile update settings.compiler.version=8 default
  conan config set general.revisions_enabled=1
}

ttp_pkg() {
  cd "${SRC}/takthirdparty"
  ln -sfn "builds/android-${ABI}-release" "android-${ABI}-release"
  (cd ci-support && conan export-pkg . "${CONAN_S[@]}" -f && ./gradlew --no-daemon -q assemble publishToMavenLocal)
  (cd "${SRC}/takengine/thirdparty/apache-commons-lang-slim" && ./gradlew --no-daemon -q publishToMavenLocal)
}

laszip() {
  cd "${SRC}/LASzip"
  cmake -S . -B "build-android-${ABI}" "${NDK_CMAKE[@]}" -DANDROID_STL=c++_static \
    -DCMAKE_CXX_FLAGS="-fexceptions -frtti -std=c++11" -DLASZIP_BUILD_STATIC=ON
  cmake --build "build-android-${ABI}" -j"${JOBS}"
  cp -r include "build-android-${ABI}/"
  cp src/*.hpp "build-android-${ABI}/include/laszip/"
  (cd ci-support && conan export-pkg . "${CONAN_S[@]}" -f)
}

liblas() {
  cd "${SRC}/libLAS"
  cmake -S . -B "build-android-${ABI}" "${NDK_CMAKE[@]}" -DANDROID_STL=c++_static \
    -DCMAKE_CXX_FLAGS="-fexceptions -frtti -std=c++11"
  cmake --build "build-android-${ABI}" -j"${JOBS}"
  cp -r include "build-android-${ABI}/"
  (cd ci-support && conan export-pkg . "${CONAN_S[@]}" -f && ./gradlew --no-daemon -q assemble publishToMavenLocal)
}

draco() {
  cd "${SRC}/draco"
  cmake -S . -B "build-android-${ABI}" "${NDK_CMAKE[@]}" -DCMAKE_POSITION_INDEPENDENT_CODE=ON
  cmake --build "build-android-${ABI}" -j"${JOBS}"
  cp "${RECIPES}/draco/conanfile.py" .
  conan export-pkg . "${CONAN_S[@]}" -f
}

headers() {
  cd "${SRC}/takengine/thirdparty/tinygltf"
  rm -rf draco-include && mkdir -p draco-include/draco
  cp -r "${SRC}/draco/src/draco/." draco-include/draco/
  cp "${SRC}/draco/build-android-${ABI}/draco/draco_features.h" draco-include/draco/
  cp "${RECIPES}/tinygltf/conanfile.py" . && conan export-pkg . -f
  (cd ../tinygltfloader && conan export-pkg . -f)
  (cd "${SRC}/khronos" && cp "${RECIPES}/khronos/conanfile.py" . && conan export-pkg . -f)
}

cesium() {
  cd "${SRC}/cesium-native"
  if [ ! -d cesium-native ]; then
    git clone -q --depth 1 --branch "${CESIUM_REF}" --recurse-submodules --shallow-submodules \
      https://github.com/CesiumGS/cesium-native.git cesium-native
  fi
  # stage.sh pulls the zlib-ng port from vcpkg master. Pin it to the vcpkg
  # commit cesium-native itself builds against.
  ref="$(grep -oE '[0-9a-f]{40}' cesium-native/CMakeLists.txt | head -1)"
  [ -n "${ref}" ] && sed -i "s#refs/heads/master#${ref}#g" overlay-ports/stage.sh
  WARNINGS_AS_ERRORS=OFF ANDROID_ABI="${ABI}" ./build-android.sh
  cp "${RECIPES}/cesium-native/conanfile.py" .
  conan export-pkg . "${CONAN_S[@]}" -f
}

phases=("$@")
[ ${#phases[@]} -eq 0 ] && phases=(extract ttp conan_profile ttp_pkg laszip liblas draco headers cesium)
for p in "${phases[@]}"; do
  log "start ${p}"
  "${p}"
  log "done ${p}"
done
