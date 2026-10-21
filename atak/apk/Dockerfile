# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# Builds the ATAK-CIV debug APK from the public source pinned by the
# upstream/atak-civ submodule (tag 5.5.1.10). One ABI (x86_64) because the APK
# runs in an x86_64 Android VM. Build context is the repository root with the
# submodule's LFS files pulled.
#
#   docker buildx build -f atak/apk/Dockerfile --target apk --output type=local,dest=out .
#
# Each prebuild phase is its own layer so a cache hit resumes at the first
# phase that changed.

# Base of the driver image (adb and python3 for UI Automator dumps).
ARG DRIVER_IMAGE=ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ARG BUILDER_IMAGE=eclipse-temurin:17.0.20_8-jdk-jammy@sha256:51d32af96fb8a13ffbc96c719d7b05447a04ca69f314627d64050a64ecd13057

FROM ${BUILDER_IMAGE} AS toolchain

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ant apg autoconf automake autopoint bison bzip2 byacc ca-certificates cmake curl \
        dos2unix file flex g++ gettext git jq libtool libxml2-dev m4 make ninja-build \
        patch patchelf pkg-config python3 python3-pip sqlite3 swig tcl unzip xz-utils zip zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# takkernel requires Conan 1.x.
RUN pip3 install --no-cache-dir "conan==1.65.0"

ENV ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_NDK=/opt/android-sdk/ndk/25.1.8937393 \
    ANDROID_NDK_HOME=/opt/android-sdk/ndk/25.1.8937393

ARG CMDLINE_TOOLS=11076708
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN mkdir -p "${ANDROID_SDK_ROOT}/cmdline-tools" \
    && curl -fsSLo /tmp/tools.zip "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS}_latest.zip" \
    && unzip -q /tmp/tools.zip -d /tmp \
    && mv /tmp/cmdline-tools "${ANDROID_SDK_ROOT}/cmdline-tools/latest" \
    && rm /tmp/tools.zip \
    && (yes || true) | "${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null \
    && "${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin/sdkmanager" --install \
        "platforms;android-35" "build-tools;35.0.0" "ndk;25.1.8937393" "cmake;3.22.1" >/dev/null

# CI builds each stage with its own --target so a later failure keeps the
# earlier stages in the cache (TAK third party alone is about 30 minutes).
FROM toolchain AS ttp
COPY upstream/atak-civ /src/atak-civ
ENV SRC=/src/atak-civ
# Same steps as prebuild.sh extract ttp, written out so that edits to the
# script do not invalidate this layer.
WORKDIR /src/atak-civ
RUN tar xzf depends/assimp-4.0.1-mod.tar.gz -C . \
    && tar xzf depends/gdal-2.4.4-mod.tar.gz -C . \
    && tar xzf depends/libLAS-1.8.2-mod.tar.gz -C . \
    && tar xzf depends/LASzip-3.4.3-mod.tar.gz -C . \
    && tar xzf depends/tinygltf-2.4.1-mod.tar.gz -C takengine/thirdparty \
    && make -C takthirdparty TARGET=android-x86_64 GDAL_USE_KDU=no \
        build_spatialite build_commoncommo build_gdal build_assimp

FROM ttp AS deps
COPY atak/apk /build
RUN /build/prebuild.sh conan_profile ttp_pkg laszip liblas draco headers

FROM deps AS cesium
RUN /build/prebuild.sh cesium

FROM cesium AS build
# The public 5.5.1.10 tree ships no assets/wms/, but AppVersionUpgrade loads
# wms/cleanup.properties on the first start after an install and crashes on
# the null stream (NullPointerException in Properties.load). An empty file
# means "no legacy map source pointers to clean up".
RUN mkdir -p /src/atak-civ/atak/ATAK/app/src/main/assets/wms \
    && touch /src/atak-civ/atak/ATAK/app/src/main/assets/wms/cleanup.properties
RUN /build/build-apk.sh \
    && cp "$(find /src/atak-civ/atak/ATAK/app/build/outputs/apk -name '*.apk' | head -1)" /atak-civ.apk

FROM scratch AS apk
COPY --from=build /atak-civ.apk /atak-civ.apk

# Test driver: adb, the APK, and atak/driver/drive.sh. No credentials; the
# Job passes them from a Secret at run time.
FROM ${DRIVER_IMAGE} AS driver
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends adb python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /atak-civ.apk /atak-civ.apk
COPY atak/driver/drive.sh /usr/local/bin/drive.sh
USER 65532
ENV HOME=/tmp
ENTRYPOINT ["/usr/local/bin/drive.sh"]
