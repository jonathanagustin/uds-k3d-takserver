#!/bin/bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Fail closed. The upstream cluster scripts exec java with no waits.
# Ignite's discovery port has to be open first. Config, messaging, and the
# API then have to be the current Deployment and Ready. Ready means the
# stock readiness script passed. A listening port is not that gate.
#
# Modes:
#   ignite    discovery port 47500, bound at 180s
#   config    ignite, then takserver-config Ready, bound at 300s
#   services  config, then messaging and the API Ready, bound at 300s each
set -euo pipefail

mode="${1:?wait mode is required}"
ns="$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)"
token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
api="https://kubernetes.default.svc.cluster.local"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to read Deployment status" >&2
  exit 1
fi
if ! command -v nc >/dev/null 2>&1; then
  echo "nc is required to reach Ignite" >&2
  exit 1
fi

wait_ignite() {
  local deadline=$((SECONDS + 180))
  echo "waiting up to 180s for takserver-ignite:47500"
  while true; do
    if nc -z -w 2 takserver-ignite 47500; then
      echo "takserver-ignite:47500 is open"
      return 0
    fi
    if [[ "${SECONDS}" -ge "${deadline}" ]]; then
      echo "takserver-ignite:47500 was not open within 180s" >&2
      exit 1
    fi
    sleep 2
  done
}

number_field() {
  local body="$1"
  local key="$2"
  local line
  # grep -o reads the whole body. head would close the pipe early.
  line="$(printf '%s' "${body}" | grep -o "\"${key}\":[0-9][0-9]*" || true)"
  line="${line%%$'\n'*}"
  printf '%s' "${line#*:}"
}

# Why the last deploy_current call said no. wait_deploy prints it, because a
# failed API call and a Deployment that is not Ready look the same otherwise.
last_reason=""

deploy_current() {
  local name="$1"
  local body spec_replicas ready updated generation observed
  # The API server pretty-prints JSON for curl clients, which breaks the
  # one-line patterns below. Ask for compact output and strip whitespace as well.
  if ! body="$(curl -fsS --max-time 15 --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" \
    "${api}/apis/apps/v1/namespaces/${ns}/deployments/${name}?pretty=false" 2>&1)"; then
    last_reason="API call failed: ${body}"
    return 1
  fi
  body="$(printf '%s' "${body}" | tr -d ' \n\t\r')"
  spec_replicas="$(number_field "${body}" replicas || true)"
  ready="$(number_field "${body}" readyReplicas || true)"
  updated="$(number_field "${body}" updatedReplicas || true)"
  generation="$(number_field "${body}" generation || true)"
  observed="$(number_field "${body}" observedGeneration || true)"
  last_reason="replicas=${spec_replicas} ready=${ready} updated=${updated} generation=${generation} observed=${observed}"
  [[ -n "${spec_replicas}" ]] || return 1
  [[ "${ready}" = "${spec_replicas}" ]] || return 1
  [[ "${updated}" = "${spec_replicas}" ]] || return 1
  [[ -n "${generation}" ]] && [[ "${observed}" = "${generation}" ]] || return 1
  if ! grep -Eq '"type":"Available","status":"True"|"status":"True","type":"Available"' <<< "${body}"; then
    last_reason="${last_reason} Available is not True"
    return 1
  fi
  return 0
}

wait_deploy() {
  local name="$1"
  local seconds="$2"
  local deadline=$((SECONDS + seconds))
  echo "waiting up to ${seconds}s for deployment/${name} to be updated and Ready"
  while true; do
    if deploy_current "${name}"; then
      echo "deployment/${name} is updated and Ready"
      return 0
    fi
    if [[ "${SECONDS}" -ge "${deadline}" ]]; then
      echo "deployment/${name} was not Ready within ${seconds}s: ${last_reason}" >&2
      exit 1
    fi
    if [[ $((SECONDS % 60)) -lt 5 ]]; then
      echo "deployment/${name} not Ready yet: ${last_reason}"
    fi
    sleep 5
  done
}

wait_ignite
case "${mode}" in
  ignite) ;;
  config)
    wait_deploy takserver-config 300
    ;;
  services)
    wait_deploy takserver-config 300
    wait_deploy takserver-messaging 300
    wait_deploy takserver-api 300
    ;;
  *)
    echo "unknown wait mode ${mode}" >&2
    exit 1
    ;;
esac
