#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# adb on the ATAK test device for the demo walkthroughs, from a short-lived
# pod with the atak-driver image and label (atak/deploy/device.yaml lets only
# that label reach the device's adb port). atak/ci/e2e.sh must have run.
#
#   demo/atak-adb.sh start       create the pod and connect adb (keeps a
#                                pod that is already connected)
#   demo/atak-adb.sh prep        shorter Android animations, ATAK in front
#   demo/atak-adb.sh zoom N      tap ATAK's + zoom button N times
#   demo/atak-adb.sh shot NAME   save the device screen to demo/out/atak/NAME.png
#   demo/atak-adb.sh record-start NAME
#                                record the device screen on the device
#                                (screenrecord, native size, up to 3 min)
#   demo/atak-adb.sh record-stop NAME
#                                stop it and save demo/out/atak/NAME-device.mp4
#                                and NAME-device.start (wall-clock start)
#   demo/atak-adb.sh stop        delete the pod
#
# ATAK keeps the view locked on its self marker (atak/driver/drive.sh), so
# zooming in keeps the device's test location in the middle of the screen.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
image="${DRIVER_IMAGE:-ghcr.io/jonathanagustin/uds-takserver/atak-driver:dev}"
device="${ATAK_ADB:-atak-device-adb.atak.svc.cluster.local:5555}"
pod=atak-demo-adb
k() { uds zarf tools kubectl "$@"; }
a() { k exec -n atak "${pod}" -- adb -s "${device}" "$@"; }

case "${1:?usage: demo/atak-adb.sh start|zoom N|shot NAME|stop}" in
  start)
    # A recording may be running through this pod: keep it when connected.
    if a get-state 2>/dev/null | grep -q device; then
      echo "adb already connected to ${device}"
      exit 0
    fi
    k delete pod -n atak "${pod}" --ignore-not-found --wait >/dev/null
    k apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${pod}
  namespace: atak
  labels:
    app.kubernetes.io/name: atak-driver
    zarf.dev/agent: ignore
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: adb
      image: ${image}
      imagePullPolicy: Never
      command: ["/bin/sh", "-c", "sleep 3600"]
      env:
        - name: HOME
          value: /tmp
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
YAML
    k wait pod -n atak "${pod}" --for condition=Ready --timeout=2m >/dev/null
    for _ in $(seq 1 10); do
      k exec -n atak "${pod}" -- adb connect "${device}" >/dev/null 2>&1 || true
      if a get-state 2>/dev/null | grep -q device; then
        echo "adb connected to ${device}"
        exit 0
      fi
      sleep 3
    done
    echo "adb could not connect to ${device}" >&2
    exit 1
    ;;
  zoom)
    a shell uiautomator dump /sdcard/demo-ui.xml >/dev/null 2>&1
    xy="$(a exec-out cat /sdcard/demo-ui.xml | python3 -c 'import re, sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
for n in root.iter("node"):
    if (n.get("resource-id") or "").endswith(":id/tak_nav_zoom"):
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", n.get("bounds")))
        print((x1 + x2) // 2, y1 + (y2 - y1) // 4)
        sys.exit(0)
sys.exit("no tak_nav_zoom on screen")')"
    for _ in $(seq 1 "${2:-1}"); do
      # shellcheck disable=SC2086
      a shell input tap ${xy}
      sleep 0.7
    done
    ;;
  shot)
    mkdir -p demo/out/atak
    a exec-out screencap -p > "demo/out/atak/${2:?name}.png"
    ;;
  prep)
    # Window and transition animations off, other animations at half: the
    # VM renders in software, and short animations stutter less.
    a shell settings put global window_animation_scale 0
    a shell settings put global transition_animation_scale 0
    a shell settings put global animator_duration_scale 0.5
    ;;
  record-start)
    mkdir -p demo/out/atak
    name="${2:?name}"
    date +%s.%N > "demo/out/atak/${name}-device.start"
    # Runs until record-stop, through the pod's adb connection.
    nohup "${BASH_SOURCE[0]}" _record "${name}" > "demo/out/atak/${name}-device.log" 2>&1 &
    echo $! > "demo/out/atak/${name}-device.pid"
    sleep 1
    ;;
  _record)
    a shell screenrecord --bit-rate 8000000 --time-limit 180 "/sdcard/${2}.mp4"
    ;;
  record-stop)
    name="${2:?name}"
    a shell pkill -INT screenrecord || true
    if [[ -f "demo/out/atak/${name}-device.pid" ]]; then
      for _ in $(seq 1 20); do
        kill -0 "$(cat "demo/out/atak/${name}-device.pid")" 2>/dev/null || break
        sleep 0.5
      done
    fi
    sleep 1
    a exec-out cat "/sdcard/${name}.mp4" > "demo/out/atak/${name}-device.mp4"
    a shell rm -f "/sdcard/${name}.mp4"
    if ! ffprobe -v error -show_entries format=duration -of csv=p=0 "demo/out/atak/${name}-device.mp4"; then
      echo "The device recording ${name} is not a playable video; the browser view is used instead." >&2
      rm -f "demo/out/atak/${name}-device.mp4"
    fi
    ;;
  stop)
    k delete pod -n atak "${pod}" --ignore-not-found --wait=false >/dev/null
    ;;
  *)
    echo "unknown command $1" >&2
    exit 2
    ;;
esac
