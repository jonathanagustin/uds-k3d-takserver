#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# End-to-end check of the ATAK test device on a cluster that `uds run
# actions:test-deploy` built (k3d cluster "uds", UDS Core slim with the
# passthrough gateway on 8446/8089, TAK Server, Keycloak user doug).
# Needs VM_IMAGE, VIEWER_IMAGE and DRIVER_IMAGE loaded in Docker.
# Evidence goes to OUT.
set -euo pipefail
OUT="${OUT:-out}"
DOMAIN="${DOMAIN:-uds.dev}"
KUBEVIRT_VERSION="${KUBEVIRT_VERSION:-v1.6.2}"
TAK_USER="${KEYCLOAK_USER:-doug}"
TAK_PASS="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}"
TAK_HOST="${TAK_HOST:-takserver-stream.${DOMAIN}}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "${OUT}"
k() { uds zarf tools kubectl "$@"; }
export VM_IMAGE VIEWER_IMAGE DOMAIN

echo "== images"
k3d image import -c uds "${VM_IMAGE}" "${VIEWER_IMAGE}" "${DRIVER_IMAGE}"

echo "== KubeVirt ${KUBEVIRT_VERSION}"
k apply -f "${here}/deploy/kubevirt-exemption.yaml"
k apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
k apply -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"
k -n kubevirt wait kv kubevirt --for condition=Available --timeout=15m

echo "== device"
k create namespace atak --dry-run=client -o yaml | k apply -f -
# shellcheck disable=SC2016 # envsubst takes the variable names literally
envsubst '${VM_IMAGE} ${VIEWER_IMAGE} ${DOMAIN}' < "${here}/deploy/device.yaml" | k apply -f -
timeout 300 sh -c 'until uds zarf tools kubectl get vmi -n atak atak-device >/dev/null 2>&1; do sleep 2; done'
k wait vmi -n atak atak-device --for condition=Ready --timeout=10m
k rollout status -n atak deploy/atak-viewer --timeout=5m

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
node "${here}/ci/viewer-sso.mjs" "https://atak.${DOMAIN}/phone.html" "${TAK_USER}" "${TAK_PASS}" "${OUT}/viewer-phone-sso.png"
