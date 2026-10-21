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

FROM toolchain AS prebuild
COPY upstream/atak-civ /src/atak-civ
COPY atak/apk /build
ENV SRC=/src/atak-civ
RUN /build/prebuild.sh extract ttp
RUN /build/prebuild.sh conan_profile ttp_pkg laszip liblas draco headers
RUN /build/prebuild.sh cesium

FROM prebuild AS build
RUN /build/build-apk.sh \
    && cp "$(find /src/atak-civ/atak/ATAK/app/build/outputs/apk -name '*.apk' | head -1)" /atak-civ.apk

FROM scratch AS apk
COPY --from=build /atak-civ.apk /atak-civ.apk
