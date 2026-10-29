#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
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
DRIVER_IMAGE="${DRIVER_IMAGE:-ghcr.io/jonathanagustin/uds-k3d-takserver/atak-driver:${ATAK_TAG}}"
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
start=$(date +%s)
pkg_dir="$(mktemp -d)"
uds zarf package create "${here}" --set ATAK_TAG="${ATAK_TAG}" -o "${pkg_dir}" --confirm
du -h "${pkg_dir}"/*.tar.zst | tee "${OUT}/package.txt"
echo "create: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
start=$(date +%s)
uds zarf package deploy "${pkg_dir}"/zarf-package-atak-device-amd64-*.tar.zst --set DOMAIN="${DOMAIN}" --confirm
echo "deploy: $(( $(date +%s) - start ))s" | tee -a "${OUT}/package.txt"
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
# ATAK with a provisioned data package. The certificate is issued here from
# the deploy-time TAK CA (cert-migration and Secret takserver-ca-key, ADR 0002) and
# exists only on this runner and in Secret atak/atak-device-dpk. TAK maps a
# client certificate to a file user by fingerprint or by CN; UserManager
# certmod adds that user with no password, as enable_admin.sh does for the
# admin certificate.
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
cm() { k get configmap cert-migration -n takserver -o "go-template={{index .binaryData \"$1\"}}" | base64 -d; }
cm ca.pem > "${work}/ca.pem"
if k get secret takserver-ca-key -n takserver >/dev/null 2>&1; then
  k get secret takserver-ca-key -n takserver -o jsonpath='{.data.ca-do-not-share\.key}' | base64 -d > "${work}/ca.key"
else
  cm ca-do-not-share.key > "${work}/ca.key"
fi
cat > "${work}/ext.cnf" <<CNF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
CNF
openssl req -new -newkey rsa:2048 -nodes -keyout "${work}/device.key" -out "${work}/device.csr" \
  -subj "/CN=${DEVICE_USER}/O=TAK/OU=UDS"
openssl x509 -req -in "${work}/device.csr" -days 30 -sha256 \
  -CA "${work}/ca.pem" -CAkey "${work}/ca.key" -passin "pass:${key_pass}" \
  -set_serial "0x$(openssl rand -hex 16)" -extfile "${work}/ext.cnf" -out "${work}/device.pem"
rm -f "${work}/ca.key"
openssl verify -CAfile "${work}/ca.pem" "${work}/device.pem"
# Android 9 reads PKCS#12 with SHA-1/3DES; OpenSSL 3 defaults to AES/PBKDF2.
P12_PASS="$(openssl rand -hex 16)"
p12() { openssl pkcs12 -export -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 -passout "pass:${P12_PASS}" "$@"; }
mkdir -p "${work}/dpk/certs" "${work}/dpk/MANIFEST"
p12 -in "${work}/device.pem" -inkey "${work}/device.key" -certfile "${work}/ca.pem" \
  -name "${DEVICE_USER}" -out "${work}/dpk/certs/${DEVICE_USER}.p12"
# -caname, not -name: with -nokeys only -caname labels the certificate, and
# Android's PKCS12 keystore lists no entry without a friendlyName.
p12 -nokeys -in "${work}/ca.pem" -caname tak-ca -out "${work}/dpk/certs/truststore.p12"
rm -f "${work}/device.key"
openssl x509 -in "${work}/device.pem" -noout -subject -enddate -fingerprint -sha256 | tee "${OUT}/device-cert.txt"

# Register the certificate in TAK with group DEVICE_GROUP. Only the public
# certificate goes into the pod.
msg() { k exec -i -n takserver deploy/takserver-messaging -c takserver-messaging -- "$@"; }
msg sh -c 'cat > /tmp/device.pem' < "${work}/device.pem"
# Same environment as enable_admin.sh, which takserver-messaging-cluster.sh
# runs after sourcing setenv.sh: the Ignite client needs its --add-opens
# flags on JDK 17. enable_admin.sh retries too.
for i in 1 2 3 4 5; do
  if msg sh -c "cd / && . ./setenv.sh && java -Xmx128m -jar UserManager.jar certmod -g '${DEVICE_GROUP}' /tmp/device.pem" < /dev/null \
    > "${OUT}/certmod.txt" 2>&1; then
    break
  fi
  [[ "${i}" = 5 ]] && { cat "${OUT}/certmod.txt" >&2; exit 1; }
  sleep 10
done
cat "${OUT}/certmod.txt"
msg rm -f /tmp/device.pem
admin "https://takserver-api.${DOMAIN}:28443/user-management/api/get-groups-for-user/${DEVICE_USER}" \
  | tee "${OUT}/device-groups.json"; echo

# A standard ATAK connection data package: one 8089 ssl stream with the
# truststore and client certificate it ships with.
cat > "${work}/dpk/certs/server.pref" <<PREF
<?xml version='1.0' standalone='yes'?>
<preferences>
  <preference version="1" name="cot_streams">
    <entry key="count" class="class java.lang.Integer">1</entry>
    <entry key="description0" class="class java.lang.String">TAK Server</entry>
    <entry key="enabled0" class="class java.lang.Boolean">true</entry>
    <entry key="connectString0" class="class java.lang.String">${TAK_HOST}:8089:ssl</entry>
    <entry key="caLocation0" class="class java.lang.String">cert/truststore.p12</entry>
    <entry key="caPassword0" class="class java.lang.String">${P12_PASS}</entry>
    <entry key="certificateLocation0" class="class java.lang.String">cert/${DEVICE_USER}.p12</entry>
    <entry key="clientPassword0" class="class java.lang.String">${P12_PASS}</entry>
  </preference>
  <preference version="1" name="com.atakmap.app_preferences">
    <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
  </preference>
</preferences>
PREF
cat > "${work}/dpk/MANIFEST/manifest.xml" <<XML
<MissionPackageManifest version="2">
  <Configuration>
    <Parameter name="uid" value="$(cat /proc/sys/kernel/random/uuid)"/>
    <Parameter name="name" value="${DEVICE_USER}"/>
    <Parameter name="onReceiveDelete" value="true"/>
  </Configuration>
  <Contents>
    <Content ignore="false" zipEntry="certs/server.pref"/>
    <Content ignore="false" zipEntry="certs/truststore.p12"/>
    <Content ignore="false" zipEntry="certs/${DEVICE_USER}.p12"/>
  </Contents>
</MissionPackageManifest>
XML
(cd "${work}/dpk" && python3 -m zipfile -c "${work}/atak-device.dpk" MANIFEST certs)
unzip -l "${work}/atak-device.dpk" | tee "${OUT}/dpk-contents.txt"
unset P12_PASS

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
k logs -n atak atak-driver | tee "${OUT}/driver.log"
for f in atak-first-start.png atak-map.png atak-imported.png atak-connected.png atak-test-location.png ui.xml logcat.txt exit \
  cert-dialog.txt cert-dialog.png; do
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
