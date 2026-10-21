#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Turns the Android-x86 ISO into a disk for a KubeVirt containerDisk.
# KubeVirt boots the ISO's kernel and initrd directly, so the disk needs no
# bootloader or partition table, and mkfs -d fills it without a loop mount.
set -euo pipefail

ISO=${ISO:?path to the Android-x86 ISO}
OUT=${OUT:-/out}
SIZE=${SIZE:-8G}

work="$(mktemp -d)"
mkdir -p "${work}/iso" "${work}/rd" "${work}/fs/android/data" "${OUT}/boot" "${OUT}/disk"
7z x -o"${work}/iso" "${ISO}" kernel initrd.img ramdisk.img system.sfs >/dev/null

# adbd listens on TCP 5555 so the in-cluster driver can reach it. Only the
# driver and viewer pods may connect (NetworkPolicy). Nothing else changes.
(cd "${work}/rd" && zcat ../iso/ramdisk.img | cpio -id --quiet)
printf '%s\n' 'service.adb.tcp.port=5555' 'persist.adb.tcp.port=5555' 'persist.sys.usb.config=adb' 'ro.adb.secure=0' >> "${work}/rd/default.prop"
(cd "${work}/rd" && find . | LC_ALL=C sort | cpio -o -H newc --quiet --reproducible | gzip -9n > ../fs/android/ramdisk.img)
cp "${work}/iso/system.sfs" "${work}/fs/android/"

truncate -s "${SIZE}" "${work}/disk.raw"
E2FSPROGS_FAKE_TIME=1585106936 mkfs.ext4 -q -F -L android -U clear -E root_owner=0:0,hash_seed=00000000-0000-0000-0000-000000000000 \
  -d "${work}/fs" "${work}/disk.raw"
qemu-img convert -c -O qcow2 "${work}/disk.raw" "${OUT}/disk/android.qcow2"
cp "${work}/iso/kernel" "${OUT}/boot/kernel"
cp "${work}/iso/initrd.img" "${OUT}/boot/initrd.img"
rm -rf "${work}"
ls -la "${OUT}/boot" "${OUT}/disk"
