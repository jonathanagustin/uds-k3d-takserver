#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# QUIC through Envoy Gateway. With quic.enabled false the UDP Service is
# absent and this exits 0. With it true, a client in the k3d node network
# namespace connects to the gateway's UDP 8090, requires a refusal when it
# presents no certificate, and holds a stream open with the admin certificate
# until /Marti/api/subscriptions/all lists the CoT uid.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

kctl() {
  if command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  elif [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

if ! kctl get svc takserver-messaging-quic -n takserver >/dev/null 2>&1; then
  # The test bundle selects Envoy Gateway only to carry QUIC. With Envoy
  # Gateway installed and no QUIC Service, quic.enabled did not reach the chart.
  if kctl get package envoy-gateway -n envoy-gateway-system >/dev/null 2>&1; then
    echo "Envoy Gateway is installed but Service takserver-messaging-quic does not exist; quic.enabled did not reach the chart" >&2
    exit 1
  fi
  echo "QUIC is off. Service takserver-messaging-quic does not exist."
  exit 0
fi

# TAK 5.7-RELEASE-14 bundles the QUIC native library for linux-x86_64 only
# (src/takserver-core/build.gradle), so the QUIC input cannot start on arm64.
arch="$(kctl get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
if [[ "${arch}" != "amd64" ]]; then
  echo "SKIP QUIC on ${arch}: TAK ships the QUIC native library for linux-x86_64 only."
  exit 0
fi

# UDP counters on both ends of the gateway hop. Udp InDatagrams in the TAK
# pod's network namespace counts packets that reached it, and OutDatagrams
# counts its replies. The Envoy udp stats count what the proxy received and
# sent upstream.
udp_counters() {
  set +e
  local pod proxy
  pod="$(kctl get pods -n takserver -l app=takserver-messaging -o jsonpath='{.items[0].metadata.name}')"
  echo "UDP counters ($1), ${pod}:" >&2
  kctl exec -n takserver "${pod}" -c takserver-messaging -- sh -c 'grep "^Udp:" /proc/net/snmp' >&2
  proxy="$(kctl get pods -n envoy-default-gateway -o jsonpath='{.items[0].metadata.name}')"
  if [[ -n "${proxy}" ]]; then
    kctl port-forward -n envoy-default-gateway "pod/${proxy}" 19100:19000 >/dev/null 2>&1 &
    local pf=$!
    sleep 3
    echo "Envoy udp stats ($1), ${proxy}:" >&2
    curl -sS --max-time 5 http://127.0.0.1:19100/stats | grep -E '^(udp\.|cluster\.udproute)' | grep -v ': 0$' >&2
    kill "${pf}" >/dev/null 2>&1
    wait "${pf}" 2>/dev/null
  fi
  set -e
}

# What to look at when QUIC fails: the gateway and route status, the UDP
# Services and policies, whether TAK bound UDP 8090, and its QUIC log lines.
diagnose() {
  set +e
  echo "::group::QUIC diagnostics" >&2
  udp_counters "after"
  kctl get gateway -n envoy-default-gateway -o yaml >&2
  kctl get udproute -A -o yaml >&2
  kctl get svc,endpointslices -n envoy-default-gateway -o wide >&2
  kctl get endpointslices -n takserver -l kubernetes.io/service-name=takserver-messaging-quic -o yaml >&2
  kctl get networkpolicy -n takserver -o name | grep -i -E 'udp|envoy|quic' >&2
  for np in $(kctl get networkpolicy -n takserver -o name | grep -i -E 'udp|envoy|quic'); do
    kctl get "${np}" -n takserver -o yaml >&2
  done
  local pod
  pod="$(kctl get pods -n takserver -l app=takserver-messaging -o jsonpath='{.items[0].metadata.name}')"
  # 8090 is 1F9A in /proc/net/udp.
  echo "UDP sockets in ${pod} (8090 = :1F9A):" >&2
  kctl exec -n takserver "${pod}" -c takserver-messaging -- sh -c 'cat /proc/net/udp /proc/net/udp6 2>/dev/null' >&2
  kctl exec -n takserver "${pod}" -c takserver-messaging -- sh -c 'grep -i -h quic /opt/tak/logs/*.log 2>/dev/null | tail -40' >&2
  kctl logs -n takserver "${pod}" -c takserver-messaging --tail=2000 | grep -i quic | tail -20 >&2
  for proxy in $(kctl get pods -n envoy-default-gateway -o name); do
    kctl logs -n envoy-default-gateway "${proxy}" -c envoy --tail=50 >&2
  done
  echo "::endgroup::" >&2
  set -e
}

work="$(mktemp -d)"
cleanup() {
  if [[ -n "${hold_pid:-}" ]]; then
    kill "${hold_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf "${work}"
}
trap cleanup EXIT

echo "waiting for the Envoy default gateway"
kctl wait --for=condition=Available deployment --all -n envoy-gateway-system --timeout=300s
for _ in $(seq 1 60); do
  if kctl get gateway -n envoy-default-gateway envoy-default-gateway >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

gw_ip=""
gw_port="8090"
for _ in $(seq 1 30); do
  while read -r name; do
    [[ -z "${name}" ]] && continue
    ports="$(kctl get svc -n envoy-default-gateway "${name}" -o json)"
    found="$(printf '%s' "${ports}" | python3 -c '
import json, sys
svc = json.load(sys.stdin)
for port in svc.get("spec", {}).get("ports", []):
    if port.get("port") == 8090 and port.get("protocol") == "UDP":
        print(svc["spec"]["clusterIP"])
        raise SystemExit(0)
raise SystemExit(1)
' || true)"
    if [[ -n "${found}" ]]; then
      gw_ip="${found}"
      break
    fi
  done < <(kctl get svc -n envoy-default-gateway -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
  if [[ -n "${gw_ip}" ]]; then
    break
  fi
  sleep 5
done

if [[ -z "${gw_ip}" ]]; then
  echo "no UDP 8090 Service in envoy-default-gateway" >&2
  diagnose
  exit 1
fi
echo "Envoy Gateway UDP ${gw_ip}:${gw_port}"

node="$(docker ps -q --filter name=k3d-uds-server --filter status=running | head -n 1)"
if [[ -z "${node}" ]]; then
  echo "k3d server container not found; QUIC needs its network namespace" >&2
  exit 1
fi
pid="$(docker inspect -f '{{.State.Pid}}' "${node}")"

run_net() {
  if nsenter -t "${pid}" -n true >/dev/null 2>&1; then
    nsenter -t "${pid}" -n -- "$@"
  else
    sudo -n nsenter -t "${pid}" -n -- "$@"
  fi
}

if command -v uv >/dev/null 2>&1; then
  uv venv --python python3 "${work}/venv"
  uv pip install --python "${work}/venv/bin/python" -r "${script_dir}/requirements-quic.txt"
else
  python3 -m venv "${work}/venv"
  "${work}/venv/bin/python" -m pip install --disable-pip-version-check --no-input -r "${script_dir}/requirements-quic.txt"
fi

cert_dir="$("${script_dir}/extract-certs.sh" "${work}/certs")"
export TAK_CLIENT_KEY_PASSPHRASE
TAK_CLIENT_KEY_PASSPHRASE="$("${script_dir}/keystore-pass.sh")"
# sudo nsenter drops the environment, so the client reads the passphrase
# from a file in this mount namespace instead of from the variable.
key_pass_file="${work}/key-pass"
printf '%s' "${TAK_CLIENT_KEY_PASSPHRASE}" > "${key_pass_file}"
chmod 600 "${key_pass_file}"

udp_counters "before"
echo "client without a certificate"
reject_failed=""
if ! run_net "${work}/venv/bin/python" "${script_dir}/quic-cot.py" reject --host "${gw_ip}" --port "${gw_port}"; then
  echo "QUIC did not refuse a client with no certificate with a TLS alert" >&2
  diagnose
  # Keep going so the log also shows whether a client with a certificate
  # gets through. The test still fails at the end.
  reject_failed=1
fi

uid="uds-quic-$(date +%s)"
ready="${work}/ready"
stop="${work}/stop"
run_net "${work}/venv/bin/python" "${script_dir}/quic-cot.py" roundtrip \
  --host "${gw_ip}" --port "${gw_port}" \
  --cert "${cert_dir}/admin.pem" --key "${cert_dir}/admin.key" \
  --pass-file "${key_pass_file}" \
  --uid "${uid}" --ready "${ready}" --stop "${stop}" &
hold_pid=$!

for _ in $(seq 1 40); do
  if [[ -s "${ready}" ]]; then
    break
  fi
  if ! kill -0 "${hold_pid}" >/dev/null 2>&1; then
    wait "${hold_pid}" || true
    echo "QUIC client exited before the stream was ready" >&2
    diagnose
    exit 1
  fi
  sleep 1
done
if [[ ! -s "${ready}" ]]; then
  echo "QUIC client did not report a CoT event" >&2
  diagnose
  exit 1
fi

port="443"
if [[ -f /tmp/tak-gateway-port ]]; then
  port="$(cat /tmp/tak-gateway-port)"
fi
listed=""
for _ in $(seq 1 15); do
  body="$(curl -k -sS --max-time 20 \
    --cert "${cert_dir}/admin.pem" --key "${cert_dir}/admin.key" --pass "${TAK_CLIENT_KEY_PASSPHRASE}" \
    --resolve "takserver-api.uds.dev:${port}:127.0.0.1" \
    "https://takserver-api.uds.dev:${port}/Marti/api/subscriptions/all" || true)"
  if grep -q "${uid}" <<< "${body}"; then
    listed=1
    break
  fi
  sleep 2
done
printf 'stop\n' > "${stop}"
wait "${hold_pid}" || true
if [[ -z "${listed}" ]]; then
  echo "QUIC client ${uid} was not listed in /Marti/api/subscriptions/all" >&2
  diagnose
  exit 1
fi
echo "QUIC client ${uid} listed in /Marti/api/subscriptions/all"
if [[ -n "${reject_failed}" ]]; then
  echo "QUIC accepted the certificate client, but the client with no certificate was not refused with a TLS alert" >&2
  exit 1
fi
