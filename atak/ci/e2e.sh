#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# End-to-end check of the ATAK test device on a cluster that `uds run
# actions:test-deploy` built (k3d cluster "uds", UDS Core slim with the
# passthrough gateway on 8446/8089, TAK Server, Keycloak user doug).
# Needs the atak-civ-vm, atak-viewer and atak-driver images for ATAK_TAG in
# Docker; the Zarf package build takes the first two from there. Evidence
# goes to OUT. The device gets a client certificate at run time; no key,
# certificate or password is in any image.
set -euo pipefail
OUT="${OUT:-out}"
DOMAIN="${DOMAIN:-uds.dev}"
ATAK_TAG="${ATAK_TAG:-dev}"
DRIVER_IMAGE="${DRIVER_IMAGE:-ghcr.io/jonathanagustin/uds-takserver/atak-driver:${ATAK_TAG}}"
TAK_USER="${KEYCLOAK_USER:-doug}"
TAK_PASS="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}"
TAK_HOST="${TAK_HOST:-takserver-stream.${DOMAIN}}"
# The VM has no GPS. ATAK's "restore location on restart" settings give the
# device a fixed self position: a test location on the National Mall in
# Washington, DC, never a real fix. The callsign says so wherever it shows.
TEST_LAT="${TEST_LAT:-38.8895}"
TEST_LON="${TEST_LON:--77.0353}"
CALLSIGN="${CALLSIGN:-ATAK-DEVICE (TEST LOCATION)}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "${OUT}"
k() { uds zarf tools kubectl "$@"; }

echo "== Zarf package (KubeVirt, VM, viewer)"
# ATAK_PACKAGE (oci://...) is a package an earlier run created from the same
# inputs and published (see device-images.sh package-ref). Deploying it skips
# the create. Otherwise the package is created here, in PKG_DIR.
if [[ -n "${ATAK_PACKAGE:-}" ]]; then
  echo "package: ${ATAK_PACKAGE}" | tee "${OUT}/package.txt"
  start=$(date +%s)
  uds zarf package deploy "${ATAK_PACKAGE}" --set DOMAIN="${DOMAIN}" --confirm
  echo "deploy (pull from OCI): $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
else
  start=$(date +%s)
  pkg_dir="${PKG_DIR:-$(mktemp -d)}"
  mkdir -p "${pkg_dir}"
  uds zarf package create "${here}" --set ATAK_TAG="${ATAK_TAG}" -o "${pkg_dir}" --confirm
  du -h "${pkg_dir}"/*.tar.zst | tee "${OUT}/package.txt"
  echo "create: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
  start=$(date +%s)
  uds zarf package deploy "${pkg_dir}"/zarf-package-atak-device-amd64-*.tar.zst --set DOMAIN="${DOMAIN}" --confirm
  echo "deploy: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
fi
# The driver is a test tool, not part of the package. k3d can report a
# successful import that left nothing in the node's containerd, so check the
# node and retry with a direct import. The pod never pulls it.
driver_present() {
  docker exec k3d-uds-server-0 crictl images -o json 2>/dev/null | grep -q "\"${DRIVER_IMAGE}\""
}
for mode in tools-node direct direct; do
  k3d image import -c uds --mode "${mode}" "${DRIVER_IMAGE}"
  if driver_present; then break; fi
  echo "driver image is not in the k3d node after a ${mode} import" >&2
  sleep 5
done
driver_present || { docker exec k3d-uds-server-0 crictl images >&2 || true; exit 1; }

echo "== device certificate"
# The device authenticates to 8089 with a client certificate, like a fielded
# ATAK with a provisioned data package. A TakClient (ADR 22) issues it from
# the deploy-time TAK CA, registers the callsign in TAK group DEVICE_GROUP,
# and writes the data package to Secret takclients/<name>. The key exists
# only in that Secret, on this runner, and in Secret atak/atak-device-dpk.
k -n istio-passthrough-gateway port-forward svc/passthrough-ingressgateway 28443:443 >/tmp/e2e-pf.log 2>&1 &
pf=$!
work="$(mktemp -d)"
trap 'kill ${pf} 2>/dev/null || true; rm -rf "${work}"' EXIT
sleep 3
cert_dir="$("${here}/../tests/extract-certs.sh")"
key_pass="$("${here}/../tests/keystore-pass.sh")"
admin() {
  curl -k -sS --max-time 20 --cert "${cert_dir}/admin.pem" --key "${cert_dir}/admin.key" --pass "${key_pass}" \
    --resolve "takserver-api.${DOMAIN}:28443:127.0.0.1" "$@"
}
DEVICE_USER="${DEVICE_USER:-atak-device}"
DEVICE_GROUP="${DEVICE_GROUP:-Operators}"
k apply -f - <<YAML
apiVersion: tak.jonathanagustin.github.io/v1alpha1
kind: TakClient
metadata:
  name: ${DEVICE_USER}
  namespace: takclients
spec:
  callsign: ${DEVICE_USER}
  groups:
    - ${DEVICE_GROUP}
  validityDays: 30
YAML
if ! k wait takclient "${DEVICE_USER}" -n takclients --for=condition=Ready --timeout=300s; then
  k get takclient "${DEVICE_USER}" -n takclients -o yaml >&2
  exit 1
fi
k get takclient "${DEVICE_USER}" -n takclients -o jsonpath='{.status.conditions[0].message}{"\n"}' | tee "${OUT}/takclient.txt"
k get secret "${DEVICE_USER}" -n takclients -o jsonpath='{.data.package\.zip}' | base64 -d > "${work}/atak-device.dpk"
k get secret "${DEVICE_USER}" -n takclients -o jsonpath='{.data.client\.pem}' | base64 -d \
  | openssl x509 -noout -subject -enddate -fingerprint -sha256 | tee "${OUT}/device-cert.txt"
admin "https://takserver-api.${DOMAIN}:28443/user-management/api/get-groups-for-user/${DEVICE_USER}" \
  | tee "${OUT}/device-groups.json"; echo
unzip -l "${work}/atak-device.dpk" | tee "${OUT}/dpk-contents.txt"

echo "== driver"
k -n atak create secret generic atak-device-dpk --from-file=atak-device.dpk="${work}/atak-device.dpk" \
  --dry-run=client -o yaml | k apply -f -
k -n atak delete secret atak-tak-user --ignore-not-found
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
      imagePullPolicy: Never
      command: ["/bin/sh", "-c", "/usr/local/bin/drive.sh; echo \$? > /out/exit; sleep 900"]
      env:
        - name: DEVICE
          value: atak-device-adb.atak.svc.cluster.local:5555
        - name: TAK_HOST
          value: ${TAK_HOST}
        - name: TEST_LAT
          value: "${TEST_LAT}"
        - name: TEST_LON
          value: "${TEST_LON}"
        - name: CALLSIGN
          value: "${CALLSIGN}"
      volumeMounts:
        - name: out
          mountPath: /out
        - name: dpk
          mountPath: /dpk
          readOnly: true
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
  volumes:
    - name: out
      emptyDir: {}
    - name: dpk
      secret:
        secretName: atak-device-dpk
YAML
k wait pod -n atak atak-driver --for condition=Ready --timeout=5m
timeout 1500 sh -c 'until uds zarf tools kubectl exec -n atak atak-driver -- test -f /out/exit; do sleep 10; done'
k logs -n atak atak-driver | .github/scripts/redact-then-filter.sh | tee "${OUT}/driver.log" || echo "omitted unsanitizable driver log" >&2
for f in atak-first-start.png atak-map.png atak-imported.png atak-connected.png atak-test-location.png ui.xml logcat.txt exit \
  cert-dialog.txt cert-dialog.png; do
  k cp "atak/atak-driver:/out/${f}" "${OUT}/${f}" || true
done
for f in driver.log ui.xml logcat.txt cert-dialog.txt exit; do
  if [[ -f "${OUT}/${f}" ]]; then
    python3 .github/scripts/redact-logs.py "${OUT}/${f}" || echo "omitted unsanitizable ${f}" >&2
  fi
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
[[ -n "${found}" ]] || { echo "device user ${DEVICE_USER} has no live subscription" >&2; exit 1; }

echo "== truststore"
# ATAK validates the imported truststore with Java's PKCS12 keystore before it
# connects. Any "Unable to validate Truststore" prompt or "Truststore invalid"
# log line fails the run, even if commo still connected.
if [[ -s "${OUT}/cert-dialog.txt" ]] || grep -Eq "Truststore invalid|Unable to validate Truststore|Cert not found for" "${OUT}/logcat.txt"; then
  cat "${OUT}/cert-dialog.txt" 2>/dev/null >&2 || true
  grep -E "Truststore invalid|Unable to validate|Cert not found for" "${OUT}/logcat.txt" >&2 || true
  echo "ATAK could not validate the truststore" >&2
  exit 1
fi
echo "no truststore prompt and no truststore errors in logcat"

echo "== test location"
# TAK keeps the latest event per client. The device reports the fixed test
# location under the test callsign.
uid="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(next((c.get("clientUid") or c.get("uid") or "" for c in d.get("data", []) if c.get("username") == sys.argv[2]), ""))' "${OUT}/subscriptions.json" "${DEVICE_USER}")"
located=""
for _ in $(seq 1 30); do
  if [[ -n "${uid}" ]] && marti "cot/xml/${uid}" > "${OUT}/device-cot.xml" 2>/dev/null &&
    python3 - "${OUT}/device-cot.xml" "${TEST_LAT}" "${TEST_LON}" "${CALLSIGN}" <<'PY'
import sys, xml.etree.ElementTree as ET
path, lat, lon, callsign = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
try:
    ev = ET.parse(path).getroot()
except ET.ParseError:
    sys.exit(1)
pt, contact = ev.find("point"), ev.find("detail/contact")
ok = (pt is not None and abs(float(pt.get("lat")) - lat) < 0.001 and abs(float(pt.get("lon")) - lon) < 0.001
      and contact is not None and contact.get("callsign") == callsign)
print(f"device at {pt.get('lat') if pt is not None else '?'}, {pt.get('lon') if pt is not None else '?'}"
      f" callsign {contact.get('callsign') if contact is not None else '?'}")
sys.exit(0 if ok else 1)
PY
  then located=1; break; fi
  sleep 10
done
[[ -n "${located}" ]] || { echo "TAK has no event from ${DEVICE_USER} at the test location" >&2; exit 1; }

echo "== viewer behind SSO"
node "${here}/ci/viewer-sso.cjs" "https://atak.${DOMAIN}/phone.html" "${TAK_USER}" "${TAK_PASS}" "${OUT}/viewer-phone-sso.png"
