#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# End-to-end check of the ATAK test device on a cluster that `uds run
# actions:test-deploy` built (k3d cluster "uds", UDS Core slim with the
# passthrough gateway on 8446/8089, TAK Server, Keycloak user doug).
# Needs the atak-civ-vm, atak-viewer and atak-driver images for ATAK_TAG in
# Docker; the Zarf package build takes the first two from there. Evidence
# goes to OUT.
set -euo pipefail
OUT="${OUT:-out}"
DOMAIN="${DOMAIN:-uds.dev}"
ATAK_TAG="${ATAK_TAG:-dev}"
DRIVER_IMAGE="${DRIVER_IMAGE:-ghcr.io/jonathanagustin/uds-k3d-takserver/atak-driver:${ATAK_TAG}}"
TAK_USER="${KEYCLOAK_USER:-doug}"
TAK_PASS="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}"
TAK_HOST="${TAK_HOST:-takserver-stream.${DOMAIN}}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "${OUT}"
k() { uds zarf tools kubectl "$@"; }

echo "== Zarf package (KubeVirt, VM, viewer)"
start=$(date +%s)
pkg_dir="$(mktemp -d)"
uds zarf package create "${here}" --set ATAK_TAG="${ATAK_TAG}" -o "${pkg_dir}" --confirm
du -h "${pkg_dir}"/*.tar.zst | tee "${OUT}/package.txt"
echo "create: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
start=$(date +%s)
uds zarf package deploy "${pkg_dir}"/zarf-package-atak-device-amd64-*.tar.zst --set DOMAIN="${DOMAIN}" --confirm
echo "deploy: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
# The driver is a test tool, not part of the package.
k3d image import -c uds "${DRIVER_IMAGE}"

echo "== TAK enrollment credentials"
# The device enrolls with HTTP Basic, like any ATAK. Record what TAK accepts.
k -n istio-passthrough-gateway port-forward svc/passthrough-ingressgateway 28446:8446 >/tmp/e2e-pf.log 2>&1 &
pf=$!
trap 'kill ${pf} 2>/dev/null || true' EXIT
sleep 3
code="$(curl -k -sS -o /dev/null -w '%{http_code}' --resolve "${TAK_HOST}:28446:127.0.0.1" \
  -u "${TAK_USER}:${TAK_PASS}" "https://${TAK_HOST}:28446/Marti/api/tls/config" || true)"
echo "basic auth with the Keycloak password on 8446: HTTP ${code}" | tee "${OUT}/enroll-auth.txt"

echo "== driver"
k -n atak create secret generic atak-tak-user --from-literal=TAK_USER="${TAK_USER}" \
  --from-literal=TAK_TOKEN="${TAK_PASS}" --dry-run=client -o yaml | k apply -f -
k apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: atak-driver
  namespace: atak
  labels:
    app.kubernetes.io/name: atak-driver
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: driver
      image: ${DRIVER_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["/bin/sh", "-c", "/usr/local/bin/drive.sh; echo \$? > /out/exit; sleep 900"]
      env:
        - name: DEVICE
          value: atak-device-adb.atak.svc.cluster.local:5555
        - name: TAK_HOST
          value: ${TAK_HOST}
      envFrom:
        - secretRef:
            name: atak-tak-user
      volumeMounts:
        - name: out
          mountPath: /out
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
  volumes:
    - name: out
      emptyDir: {}
YAML
k wait pod -n atak atak-driver --for condition=Ready --timeout=5m
timeout 1500 sh -c 'until uds zarf tools kubectl exec -n atak atak-driver -- test -f /out/exit; do sleep 10; done'
k logs -n atak atak-driver | tee "${OUT}/driver.log"
for f in atak-first-start.png atak-map.png atak-enrolled.png ui.xml logcat.txt exit; do
  k cp "atak/atak-driver:/out/${f}" "${OUT}/${f}" || true
done

echo "== TAK sees the device"
cert_dir="$("${here}/../tests/extract-certs.sh")"
gw_port="$(cat /tmp/tak-gateway-port 2>/dev/null || echo 18443)"
found=""
for _ in $(seq 1 30); do
  curl -k -sS --max-time 20 --cert "${cert_dir}/admin.pem" --key "${cert_dir}/admin.key" --pass atakatak \
    --resolve "takserver-api.${DOMAIN}:${gw_port}:127.0.0.1" \
    "https://takserver-api.${DOMAIN}:${gw_port}/Marti/api/clientEndPoints" > "${OUT}/clientEndPoints.json" || true
  if grep -q "${TAK_USER}" "${OUT}/clientEndPoints.json"; then found=1; break; fi
  sleep 10
done
cat "${OUT}/clientEndPoints.json"
[ -n "${found}" ] || { echo "device user ${TAK_USER} is not in /Marti/api/clientEndPoints" >&2; exit 1; }

echo "== viewer behind SSO"
node "${here}/ci/viewer-sso.cjs" "https://atak.${DOMAIN}/phone.html" "${TAK_USER}" "${TAK_PASS}" "${OUT}/viewer-phone-sso.png"
