#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# adb on the ATAK test device for the demo walkthroughs, from a short-lived
# pod with the atak-driver image and label (atak/deploy/device.yaml lets only
# that label reach the device's adb port). atak/ci/e2e.sh must have run.
#
#   demo/atak-adb.sh start       create the pod and connect adb
#   demo/atak-adb.sh zoom N      tap ATAK's + zoom button N times
#   demo/atak-adb.sh shot NAME   save the device screen to demo/out/atak/NAME.png
#   demo/atak-adb.sh stop        delete the pod
#
# ATAK keeps the view locked on its self marker (atak/driver/drive.sh), so
# zooming in keeps the device's test location in the middle of the screen.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
image="${DRIVER_IMAGE:-ghcr.io/jonathanagustin/uds-k3d-takserver/atak-driver:dev}"
device="${ATAK_ADB:-atak-device-adb.atak.svc.cluster.local:5555}"
pod=atak-demo-adb
k() { uds zarf tools kubectl "$@"; }
a() { k exec -n atak "${pod}" -- adb -s "${device}" "$@"; }

case "${1:?usage: demo/atak-adb.sh start|zoom N|shot NAME|stop}" in
  start)
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
  stop)
    k delete pod -n atak "${pod}" --ignore-not-found --wait=false >/dev/null
    ;;
  *)
    echo "unknown command $1" >&2
    exit 2
    ;;
esac
