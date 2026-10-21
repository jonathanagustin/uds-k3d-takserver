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
# ATAK enrolls with HTTP Basic (passIsToken is always false in
# CertificateEnrollmentClient), and TAK checks Basic against its file
# authenticator. Record whether the Keycloak password works. If it does not,
# make a TAK file user for the device with a password generated now; it lives
# only in TAK and in a Secret in this cluster.
k -n istio-passthrough-gateway port-forward svc/passthrough-ingressgateway 28446:8446 28443:443 >/tmp/e2e-pf.log 2>&1 &
pf=$!
trap 'kill ${pf} 2>/dev/null || true' EXIT
sleep 3
cert_dir="$("${here}/../tests/extract-certs.sh")"
admin() {
  curl -k -sS --max-time 20 --cert "${cert_dir}/admin.pem" --key "${cert_dir}/admin.key" --pass atakatak \
    --resolve "takserver-api.${DOMAIN}:28443:127.0.0.1" "$@"
}
basic_code() {
  curl -k -sS -o /dev/null -w '%{http_code}' --resolve "${TAK_HOST}:28446:127.0.0.1" \
    -u "$1:$2" "https://${TAK_HOST}:28446/Marti/api/tls/config" || true
}
code="$(basic_code "${TAK_USER}" "${TAK_PASS}")"
echo "basic auth with the Keycloak password on 8446: HTTP ${code}" | tee "${OUT}/enroll-auth.txt"
DEVICE_USER="${TAK_USER}"
DEVICE_PASS="${TAK_PASS}"
if [ "${code}" != "200" ]; then
  DEVICE_USER="atak-device"
  DEVICE_PASS="Atak-$(openssl rand -hex 12)-9"
  admin -X DELETE "https://takserver-api.${DOMAIN}:28443/user-management/api/delete-user/${DEVICE_USER}" >/dev/null || true
  body="$(printf '{"username":"%s","password":"%s","groupList":["atak-test"],"groupListIN":[],"groupListOUT":[]}' "${DEVICE_USER}" "${DEVICE_PASS}")"
  new_code="$(admin -o "${OUT}/new-user.txt" -w '%{http_code}' -H 'Content-Type: application/json' -X POST \
    --data "${body}" "https://takserver-api.${DOMAIN}:28443/user-management/api/new-user")"
  code="$(basic_code "${DEVICE_USER}" "${DEVICE_PASS}")"
  echo "TAK file user ${DEVICE_USER}: new-user HTTP ${new_code}, basic auth on 8446: HTTP ${code}" | tee -a "${OUT}/enroll-auth.txt"
  [ "${code}" = "200" ] || { cat "${OUT}/new-user.txt" >&2; exit 1; }
fi

echo "== driver"
k -n atak create secret generic atak-tak-user --from-literal=TAK_USER="${DEVICE_USER}" \
  --from-literal=TAK_TOKEN="${DEVICE_PASS}" --dry-run=client -o yaml | k apply -f -
k apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: atak-driver
  namespace: atak
  labels:
    app.kubernetes.io/name: atak-driver
    # The driver image is imported into k3d for the test, not carried in the
    # Zarf package, so the Zarf agent must not point it at the Zarf registry.
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
for f in atak-first-start.png atak-map.png atak-enrolled.png atak-connected.png ui.xml logcat.txt exit; do
  k cp "atak/atak-driver:/out/${f}" "${OUT}/${f}" || true
done

echo "== TAK sees the device"
# subscriptions/all is the admin view of live connections. clientEndPoints
# only lists clients that share a group with the caller, and the admin
# certificate has no groups. Either one listing the device user passes.
marti() { admin "https://takserver-api.${DOMAIN}:28443/Marti/api/$1"; }
found=""
for _ in $(seq 1 30); do
  marti subscriptions/all > "${OUT}/subscriptions.json" || true
  marti clientEndPoints > "${OUT}/clientEndPoints.json" || true
  if grep -q "\"${DEVICE_USER}\"" "${OUT}/subscriptions.json" "${OUT}/clientEndPoints.json"; then found=1; break; fi
  sleep 10
done
cat "${OUT}/subscriptions.json" "${OUT}/clientEndPoints.json"
[ -n "${found}" ] || { echo "device user ${DEVICE_USER} has no live subscription" >&2; exit 1; }

echo "== viewer behind SSO"
node "${here}/ci/viewer-sso.cjs" "https://atak.${DOMAIN}/phone.html" "${TAK_USER}" "${TAK_PASS}" "${OUT}/viewer-phone-sso.png"
