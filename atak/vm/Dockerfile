# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# KubeVirt containerDisk for the ATAK test device: Android-x86 9.0-r2
# (Android 9, API 28, x86_64). The same image carries the kernel and initrd
# for KubeVirt's kernelBoot. No keys, certificates or passwords are inside;
# ATAK gets its connection data package over adb after boot.
#
#   docker buildx build -f atak/vm/Dockerfile -t atak-civ-vm .

ARG TOOLS_IMAGE=ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

FROM ${TOOLS_IMAGE} AS disk
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates cpio curl e2fsprogs gzip p7zip-full qemu-utils \
    && rm -rf /var/lib/apt/lists/*
ARG ANDROID_X86_URL=https://sourceforge.net/projects/android-x86/files/Release%209.0/android-x86_64-9.0-r2.iso/download
ARG ANDROID_X86_SHA256=f7eb8fc56f29ad5432335dc054183acf086c539f3990f0b6e9ff58bd6df4604e
# SourceForge mirrors drop long transfers; resume until the hash matches.
RUN for i in 1 2 3 4 5 6 7 8; do \
        curl -fsSL --retry 5 --retry-all-errors -C - -o /android-x86.iso "${ANDROID_X86_URL}" && break; \
        echo "download attempt ${i} failed, resuming"; sleep 5; \
    done \
    && echo "${ANDROID_X86_SHA256}  /android-x86.iso" | sha256sum -c -
COPY atak/vm/build-disk.sh /usr/local/bin/build-disk.sh
RUN ISO=/android-x86.iso OUT=/out build-disk.sh && rm /android-x86.iso

FROM scratch
COPY --from=disk --chown=107:107 /out/disk/android.qcow2 /disk/android.qcow2
COPY --from=disk --chown=107:107 /out/boot/ /boot/
