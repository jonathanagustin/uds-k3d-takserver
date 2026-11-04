#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# TakClient end to end (ADR 22, issue #36):
# 1. Apply a TakClient for a test callsign and wait for Ready.
# 2. Read its Secret, connect on 8089 with that certificate, send one CoT
#    event, and wait until TAK lists the callsign in /Marti/api/clientEndPoints.
# 3. Delete the TakClient. The finalizer deletes the TAK user, adds the
#    serial to the CRL in Secret takserver-crl, and deletes the client's
#    Secret. UDS Core restarts the TAK pods that mount the CRL. Then 8089
#    must reject the certificate.
# Before step 1 it checks the ServiceAccounts: only the watcher account can
# read the TAK CA key, and the admission pods' account can read no Secret.
#
# The certificate and key exist only in Secret takclients/<name> and in a
# temporary directory here, which is removed on exit.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
k() { uds zarf tools kubectl "$@"; }
name="${TAKCLIENT_NAME:-takclient-test}"
domain="${DOMAIN:-uds.dev}"
work="$(mktemp -d)"
pf=""
cleanup() {
  if [[ -n "${pf}" ]]; then kill "${pf}" 2>/dev/null || true; fi
  k delete takclient "${name}" -n takclients --ignore-not-found --wait=false >/dev/null 2>&1 || true
  rm -rf "${work}"
}
trap cleanup EXIT

gw_port=""
if [[ -f /tmp/tak-gateway-port ]]; then
  gw_port="$(tr -d '[:space:]' < /tmp/tak-gateway-port)"
fi
if [[ -z "${gw_port}" ]]; then
  gw_port=28443
  k -n istio-passthrough-gateway port-forward svc/passthrough-ingressgateway "${gw_port}:443" >/tmp/takclient-pf.log 2>&1 &
  pf=$!
  sleep 3
fi

echo "== apply TakClient ${name}"
k get crd takclients.tak.jonathanagustin.github.io -o name

echo "== ServiceAccounts"
uuid="pepr-c72fcf944a4f43bbb386d22371aa640f"
admission_sa="system:serviceaccount:pepr-system:${uuid}"
watcher_sa="system:serviceaccount:pepr-system:${uuid}-watcher"
can() { k auth can-i "$@" 2>/dev/null || true; }
expect() {
  local want="$1" who="$2"; shift 2
  local got
  got="$(can "$@" --as="${who}")"
  if [[ "${got}" != "${want}" ]]; then
    echo "kubectl auth can-i $* --as=${who}: got '${got}', want '${want}'" >&2
    exit 1
  fi
}
expect yes "${watcher_sa}" get secret/takserver-ca-key -n takserver
expect yes "${watcher_sa}" create secrets -n takclients
expect no "${admission_sa}" get secret/takserver-ca-key -n takserver
expect no "${admission_sa}" list secrets --all-namespaces
expect no "${admission_sa}" get secrets -n takclients
expect no "${admission_sa}" patch takclients.tak.jonathanagustin.github.io -n takclients
expect yes "${admission_sa}" get configmap/core-config -n takserver
expect no "${watcher_sa}" get secret/takserver-db -n takserver
for app in "${uuid}:${uuid}" "${uuid}-watcher:${uuid}-watcher"; do
  account="$(k get deploy "${app%%:*}" -n pepr-system -o jsonpath='{.spec.template.spec.serviceAccountName}')"
  [[ "${account}" = "${app##*:}" ]] || { echo "deploy ${app%%:*} runs as '${account}', want '${app##*:}'" >&2; exit 1; }
done
k apply -f - <<YAML
apiVersion: tak.jonathanagustin.github.io/v1alpha1
kind: TakClient
metadata:
  name: ${name}
  namespace: takclients
spec:
  callsign: ${name}
  groups:
    - Operators
  validityDays: 2
YAML
if ! k wait takclient "${name}" -n takclients --for=condition=Ready --timeout=300s; then
  k get takclient "${name}" -n takclients -o yaml >&2
  k logs -n pepr-system -l pepr.dev/controller=watcher --tail=100 >&2 || true
  exit 1
fi
k get takclient "${name}" -n takclients -o jsonpath='{.status.conditions[0].message}{"\n"}'
finalizers="$(k get takclient "${name}" -n takclients -o jsonpath='{.metadata.finalizers}')"
grep -q 'pepr.dev/finalizer' <<< "${finalizers}" || { echo "TakClient has no Pepr finalizer: ${finalizers}" >&2; exit 1; }

secret() { k get secret "${name}" -n takclients -o "jsonpath={.data.$1}" | base64 -d; }
secret client\\.pem > "${work}/client.pem"
secret client\\.key > "${work}/client.key"
secret ca\\.pem > "${work}/ca.pem"
secret package\\.zip > "${work}/package.zip"
serial="$(k get takclient "${name}" -n takclients -o jsonpath='{.metadata.annotations.tak\.jonathanagustin\.github\.io/serial}')"
openssl verify -CAfile "${work}/ca.pem" "${work}/client.pem"
[[ "$(openssl x509 -in "${work}/client.pem" -noout -serial | cut -d= -f2 | tr 'A-F' 'a-f')" = "${serial}" ]]
python3 - "${work}/package.zip" "${name}" "takserver-stream.${domain}" <<'PY'
import sys, zipfile
path, name, host = sys.argv[1:]
names = zipfile.ZipFile(path).namelist()
want = ["MANIFEST/manifest.xml", "certs/server.pref", "certs/truststore.p12", f"certs/{name}.p12"]
assert names == want, names
pref = zipfile.ZipFile(path).read("certs/server.pref").decode()
assert f"{host}:8089:ssl" in pref, pref
print("data package:", ", ".join(names))
PY

echo "== 8089 with the TakClient certificate"
python3 - "${work}" "${gw_port}" "${name}" "${domain}" <<'PY'
import os, socket, ssl, subprocess, sys, time
work, port, uid, domain = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
cert, key = os.path.join(work, "client.pem"), os.path.join(work, "client.key")
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
ctx.load_cert_chain(cert, key)
now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
stale = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 300))
event = (f'<?xml version="1.0" encoding="UTF-8"?><event version="2.0" uid="{uid}" type="a-f-G-U-C" '
         f'how="m-g" time="{now}" start="{now}" stale="{stale}"><point lat="0" lon="0" hae="0" ce="9999999" le="9999999"/>'
         f'<detail><contact callsign="{uid}" endpoint="*:-1:stcp"/><takv platform="uds-takclient" version="1"/></detail></event>')
api = f"https://takserver-api.{domain}:{port}/Marti/api/clientEndPoints"
found = False
# A first connection can create the user's groups, and TAK 5.7 then hides
# that subscription (see tests/api-smoke.sh). Reconnect once.
for attempt in range(3):
    with socket.create_connection(("127.0.0.1", port), timeout=20) as raw:
        with ctx.wrap_socket(raw, server_hostname=f"takserver-stream.{domain}") as tls:
            tls.sendall(event.encode())
            for _ in range(10):
                time.sleep(2)
                out = subprocess.run(["curl", "-k", "-sS", "--max-time", "20", "--cert", cert, "--key", key,
                                      "--resolve", f"takserver-api.{domain}:{port}:127.0.0.1", api],
                                     capture_output=True, text=True).stdout
                if uid in out:
                    found = True
                    break
    if found:
        break
    print(f"attempt {attempt + 1}: {uid} not listed yet: {out[:500]}", file=sys.stderr)
if not found:
    sys.exit(1)
print(f"PASS {uid} connected on 8089 and is listed in /Marti/api/clientEndPoints")
PY

echo "== delete revokes access"
api_pod="$(k get pod -n takserver -l app=takserver-api -o jsonpath='{.items[0].metadata.uid}')"
k delete takclient "${name}" -n takclients --timeout=180s
if k get secret "${name}" -n takclients >/dev/null 2>&1; then
  echo "Secret takclients/${name} is still there after delete" >&2
  exit 1
fi
revoked="$(k get secret takserver-crl -n takserver -o jsonpath='{.data.revoked\.json}' | base64 -d)"
grep -q "${serial}" <<< "${revoked}" || { echo "serial ${serial} is not in takserver-crl: ${revoked}" >&2; exit 1; }
k get secret takserver-crl -n takserver -o jsonpath='{.data.ca\.crl}' | base64 -d > "${work}/ca.crl"
# openssl exits non-zero for a revoked certificate. Capture the output first,
# so pipefail does not turn that into a failed check.
verify_out="$(openssl verify -crl_check -CAfile "${work}/ca.pem" -CRLfile "${work}/ca.crl" "${work}/client.pem" 2>&1 || true)"
if grep -q "certificate revoked" <<< "${verify_out}"; then
  echo "PASS the CRL in takserver-crl revokes ${serial}"
else
  echo "the CRL does not revoke ${serial}: ${verify_out}" >&2
  exit 1
fi
# UDS Core pod-reload restarts the TAK pods that mount takserver-crl.
for _ in $(seq 1 90); do
  now_pod="$(k get pod -n takserver -l app=takserver-api -o jsonpath='{.items[0].metadata.uid}' 2>/dev/null || true)"
  if [[ -n "${now_pod}" && "${now_pod}" != "${api_pod}" ]]; then
    break
  fi
  sleep 5
done
for deploy in takserver-config takserver-messaging takserver-api takserver-plugins; do
  k rollout status "deploy/${deploy}" -n takserver --timeout=900s
done
cert_dir="$("${script_dir}/extract-certs.sh")"
key_pass="$("${script_dir}/keystore-pass.sh")"
python3 - "${work}" "${gw_port}" "${domain}" "${cert_dir}" "${key_pass}" <<'PY'
import os, socket, ssl, sys, time
work, port, domain, cert_dir, key_pass = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]

def handshake(cert, key, password=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # TLS 1.3 can return from the client handshake before a rejection arrives.
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key, password=password)
    with socket.create_connection(("127.0.0.1", port), timeout=20) as raw:
        with ctx.wrap_socket(raw, server_hostname=f"takserver-stream.{domain}"):
            return

deadline = time.time() + 600
last = ""
while time.time() < deadline:
    # The admin certificate is the control: it must still connect, so a
    # rejection below is TAK checking the CRL and not TAK being down.
    try:
        handshake(os.path.join(cert_dir, "admin.pem"), os.path.join(cert_dir, "admin.key"), key_pass)
    except (ssl.SSLError, OSError) as err:
        last = f"control certificate failed: {err}"
        time.sleep(10)
        continue
    try:
        handshake(os.path.join(work, "client.pem"), os.path.join(work, "client.key"))
        last = "handshake with the revoked certificate succeeded"
    except ssl.SSLError as err:
        print(f"PASS 8089 rejects the revoked certificate ({err.reason}); the admin certificate still connects")
        sys.exit(0)
    except OSError as err:
        last = f"revoked certificate: {err}"
    time.sleep(10)
print(f"8089 did not reject the revoked certificate: {last}", file=sys.stderr)
sys.exit(1)
PY
