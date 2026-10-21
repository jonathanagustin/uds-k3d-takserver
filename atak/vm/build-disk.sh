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
# Boot report on the serial console (kernel log): network, adb and display
# state, so CI can tell why the device is not reachable. It also makes sure
# adbd runs with the TCP port, since there is no USB gadget in the VM.
cat > "${work}/rd/atak-boot-report.sh" <<'SH'
#!/system/bin/sh
setprop service.adb.tcp.port 5555
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 20
  [ "$(getprop init.svc.adbd)" = running ] || start adbd
  # A test device: keep the screen on so screenshots are not black.
  if [ "$(getprop sys.boot_completed)" = 1 ]; then
    svc power stayon true
    settings put system screen_off_timeout 2147483647
    input keyevent KEYCODE_WAKEUP
  fi
  {
    echo "round $i boot_completed=$(getprop sys.boot_completed) adbd=$(getprop init.svc.adbd) usb=$(getprop sys.usb.config) sf=$(getprop init.svc.surfaceflinger)"
    echo "net: $(ls /sys/class/net | tr '\n' ' ')"
    ip -4 addr show 2>&1
    ip route 2>&1
    echo "dns1=$(getprop net.dns1) eth0.dns1=$(getprop dhcp.eth0.dns1)"
    netstat -ltn 2>&1 | grep -E ':5555|Proto'
    logcat -d -b crash -t 20 2>&1
    logcat -d -t 400 2>&1 | grep -iE 'surfaceflinger|gralloc|EGL|adbd|FATAL' | tail -n 25
  } | while IFS= read -r l; do echo "atak-report: $l" > /dev/kmsg; done
done
SH
chmod 0755 "${work}/rd/atak-boot-report.sh"
cat >> "${work}/rd/init.rc" <<'RC'

service atak-boot-report /system/bin/sh /atak-boot-report.sh
    class late_start
    user root
    group root shell log
    seclabel u:r:su:s0
    oneshot
RC
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
