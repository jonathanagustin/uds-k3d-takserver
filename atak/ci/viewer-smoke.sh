#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Runs the browser viewer against the device VM started by vm-smoke.sh and
# saves a screenshot of the phone page. Needs VIEWER_IMAGE imported into k3d.
set -euo pipefail
: "${VIEWER_IMAGE:?}"
NS="${NS:-atak}"
OUT="${OUT:-out}"
mkdir -p "${OUT}"
ip="$(kubectl get vmi -n "${NS}" atak-device -o jsonpath='{.status.interfaces[0].ipAddress}')"

kubectl apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: atak-viewer
  namespace: ${NS}
  labels:
    app.kubernetes.io/name: atak-viewer
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: viewer
      image: ${VIEWER_IMAGE}
      imagePullPolicy: IfNotPresent
      env:
        - name: DEVICE
          value: "${ip}:5555"
      ports:
        - containerPort: 8000
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
YAML
kubectl wait pod -n "${NS}" atak-viewer --for condition=Ready --timeout=5m
kubectl port-forward -n "${NS}" pod/atak-viewer 8000:8000 >/tmp/pf.log 2>&1 &
pf=$!
trap 'kill ${pf} 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -fsS -o /dev/null http://127.0.0.1:8000/phone.html && break; sleep 2; done
# Give adb in the viewer time to connect before the page asks for the stream.
sleep 15
npx -y playwright@1.56.1 screenshot --channel chrome --viewport-size "560,1000" \
  --wait-for-timeout 25000 http://127.0.0.1:8000/phone.html "${OUT}/viewer-phone.png"
kubectl logs -n "${NS}" atak-viewer --tail=100 > "${OUT}/viewer.log" || true
ls -la "${OUT}"
