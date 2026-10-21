#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Assembles the ATAK-CIV debug APK after prebuild.sh has run.
set -euo pipefail

SRC=${SRC:-/src/atak-civ}
ABI=${ABI:-x86_64}

cd "${SRC}/atak"
cat > local.properties <<PROPS
sdk.dir=${ANDROID_SDK_ROOT}
ndk.dir=${ANDROID_NDK}
cmake.dir=${ANDROID_SDK_ROOT}/cmake/3.22.1
ndkAbiFilter=${ABI}
kernelBuildTarget=android
PROPS
cp local.properties ATAK/local.properties
./gradlew --no-daemon --stacktrace assembleCivDebug
find ATAK/app/build/outputs/apk -name '*.apk' -exec ls -la {} +
