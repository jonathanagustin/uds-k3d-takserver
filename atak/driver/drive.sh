#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Drives the ATAK test device over adb the way a person would: installs the
# APK, gets through first-run prompts, and imports a TAK connection data
# package (8089 ssl stream, truststore and client certificate) the way a
# fielded device does: ATAK imports Download/atak*.dpk when it starts. The
# package arrives at run time from a Secret mounted at DPK; nothing is stored
# in any image. Screenshots and a UI dump go to OUT.
set -euo pipefail
DEVICE="${DEVICE:?host:port of the device adb listener}"
DPK="${DPK:-/dpk/atak-device.dpk}"
test -s "${DPK}"
APK="${APK:-/atak-civ.apk}"
OUT="${OUT:-/out}"
PKG="${PKG:-com.atakmap.app.civ}"
mkdir -p "${OUT}"
a() { adb -s "${DEVICE}" "$@"; }

shot() { a exec-out screencap -p > "${OUT}/$1.png" || true; }

# Taps the first button whose text matches one of the given labels.
# Returns 1 when none is on screen.
tap() {
  a shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 || return 1
  a exec-out cat /sdcard/ui.xml > /tmp/ui.xml 2>/dev/null || return 1
  local xy
  xy="$(python3 - "$@" <<'PY'
import re, sys, xml.etree.ElementTree as ET
labels = [l.lower() for l in sys.argv[1:]]
try:
    root = ET.parse("/tmp/ui.xml").getroot()
except ET.ParseError:
    sys.exit(1)
for n in root.iter("node"):
    # ATAK labels some buttons with a full stop ("I agree.").
    t = (n.get("text") or n.get("content-desc") or "").strip().rstrip(".!").lower()
    if t in labels and n.get("enabled") == "true":
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", n.get("bounds")))
        print((x1 + x2) // 2, (y1 + y2) // 2)
        sys.exit(0)
sys.exit(1)
PY
)" || return 1
  echo "tap ${xy}"
  # shellcheck disable=SC2086
  a shell input tap ${xy}
  sleep 2
}

for _ in $(seq 1 60); do
  adb connect "${DEVICE}" >/dev/null 2>&1 || true
  if [ "$(a shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then break; fi
  sleep 5
done
a shell svc power stayon true || true
a shell input keyevent KEYCODE_WAKEUP || true
a shell wm dismiss-keyguard || true
# The image marks the device provisioned, but Google's setup wizard in the
# Android-x86 build still starts its upgrade flow over the first app
# launched ("Hi there"). A provisioned phone would not show it.
a shell pm disable-user --user 0 com.google.android.setupwizard || true
a shell am force-stop com.google.android.setupwizard || true

start=$(date +%s)
a install -r -g "${APK}"
echo "install seconds: $(($(date +%s) - start))"
a shell pm list packages | grep -q "${PKG}"

a shell monkey -p "${PKG}" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 20
shot atak-first-start
# First run: EULA, permission rationale, tips. Keep tapping while a known
# button is on screen.
idle=0
for _ in $(seq 1 40); do
  if tap "i agree" "agree" "accept" "ok" "allow" "allow all the time" "while using the app" \
    "continue" "next" "done" "got it" "close" "dismiss" "skip"; then
    idle=0
  else
    idle=$((idle + 1))
    [ "${idle}" -ge 6 ] && break
    sleep 5
  fi
done
shot atak-map

# Hand the data package to ATAK and restart it so the start-up scan of the
# Download folder picks it up. ATAK deletes the copy in Download once it is
# queued for import.
a shell mkdir -p /sdcard/Download
a push "${DPK}" /sdcard/Download/atak-device.dpk >/dev/null
a shell am force-stop "${PKG}"
a shell monkey -p "${PKG}" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 30
for _ in $(seq 1 10); do
  tap "yes" "ok" "import" "accept" "connect" || sleep 3
done
echo "Download after import: $(a shell ls /sdcard/Download 2>&1 | tr -d '\r' | tr '\n' ' ')"
echo "ATAK cert directory: $(a shell ls /sdcard/atak/cert 2>&1 | tr -d '\r' | tr '\n' ' ')"
shot atak-imported
# TAK 5.7 can store a user's first connection without the groups it creates
# during that connection, which hides the device from contact lists. A real
# device reconnects often; restart ATAK once so the stream reconnects.
a shell am force-stop "${PKG}"
a shell monkey -p "${PKG}" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 60
shot atak-connected
if a shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; then
  a exec-out cat /sdcard/ui.xml > "${OUT}/ui.xml" || true
fi
a logcat -d -t 3000 > "${OUT}/logcat.txt" 2>&1 || true
grep -E "ImportManager|MissionPackage|Import.*Sort|CertificateManager|TAKServer|CommsMapComponent|AndroidRuntime" "${OUT}/logcat.txt" | tail -n 60 || true
