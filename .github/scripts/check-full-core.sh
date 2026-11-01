#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Wait until each functional-layer workload is Ready, then record kubectl top
# for TAK and CloudTAK. The top file is written before the comparison, so a
# failed recheck still leaves the artifact the workflow uploads.
set -euo pipefail

k() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${root}"

layers=(
  metrics-server
  loki
  vector
  falco
  velero
  monitoring
  grafana
  uds-portal
)

for ns in "${layers[@]}"; do
  if ! k get namespace "${ns}" >/dev/null 2>&1; then
    echo "namespace ${ns} does not exist" >&2
    exit 1
  fi
  echo "::group::${ns}"
  k get pods -n "${ns}" -o wide || true
  mapfile -t workloads < <(k get deploy,sts,ds -n "${ns}" -o name 2>/dev/null || true)
  if [[ "${#workloads[@]}" -eq 0 ]]; then
    echo "namespace ${ns} has no Deployment, StatefulSet, or DaemonSet" >&2
    exit 1
  fi
  for workload in "${workloads[@]}"; do
    [[ -z "${workload}" ]] && continue
    echo "waiting for ${ns} ${workload}"
    if ! k rollout status "${workload}" -n "${ns}" --timeout=600s; then
      k describe "${workload}" -n "${ns}" || true
      k get pods -n "${ns}" -o wide || true
      exit 1
    fi
  done
  k get pods -n "${ns}" -o json | python3 .github/scripts/full-core-top.py ready "${ns}"
  echo "::endgroup::"
done

resources="$(k api-resources --api-group=velero.io 2>/dev/null || true)"
if grep -q backupstoragelocations <<< "${resources}"; then
  echo "Velero BackupStorageLocation (not a pod readiness check):"
  k get backupstoragelocations.velero.io -n velero || true
  echo "fit-runner scales MinIO to 0. Velero's default bucket URL points at that MinIO, so this location can stay Unavailable while the Velero pods are Ready."
fi

out_dir="${TOP_OUT:-out}"
mkdir -p "${out_dir}"
top_file="${out_dir}/kubectl-top.txt"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

for ns in takserver cloudtak; do
  if ! k get namespace "${ns}" >/dev/null 2>&1; then
    echo "namespace ${ns} does not exist" >&2
    exit 1
  fi
  got=0
  for _ in $(seq 1 36); do
    if k top pods -n "${ns}" --no-headers > "${work}/top-${ns}.txt" 2>"${work}/top-${ns}.err"; then
      if [[ -s "${work}/top-${ns}.txt" ]] && grep -Eq '[0-9]+(Ki|Mi|Gi)' "${work}/top-${ns}.txt"; then
        # A pod replaced a moment ago (the NATS restart test does this) has no
        # metrics sample yet. Wait until every Running pod has a row.
        missing=0
        while read -r pod_name; do
          [[ -z "${pod_name}" ]] && continue
          if ! awk -v n="${pod_name}" '$1 == n { found = 1 } END { exit !found }' "${work}/top-${ns}.txt"; then
            missing=1
            echo "waiting for kubectl top to report ${ns}/${pod_name}" >&2
          fi
        done < <(k get pods -n "${ns}" --field-selector=status.phase=Running -o custom-columns=NAME:.metadata.name --no-headers 2>/dev/null || true)
        if [[ "${missing}" -eq 0 ]]; then
          got=1
          break
        fi
      fi
    fi
    sleep 10
  done
  if [[ "${got}" -ne 1 ]]; then
    echo "kubectl top pods -n ${ns} did not return numeric usage" >&2
    cat "${work}/top-${ns}.err" >&2 || true
    cat "${work}/top-${ns}.txt" >&2 || true
    exit 1
  fi
  k get pods -n "${ns}" -o json > "${work}/pods-${ns}.json"
done

{
  echo "# kubectl top pods -n takserver"
  cat "${work}/top-takserver.txt"
  echo
  echo "# kubectl top pods -n cloudtak"
  cat "${work}/top-cloudtak.txt"
} > "${top_file}"

k get sts takserver-ignite -n takserver -o json > "${work}/ignite.json"
k get deploy takserver-plugins -n takserver -o json > "${work}/plugins.json"
k get deploy takserver-config -n takserver -o json > "${work}/config.json"

# One top file for the checker. The namespace headings are comments and skipped.
python3 .github/scripts/full-core-top.py top \
  --top-file "${top_file}" \
  --pods "takserver=${work}/pods-takserver.json" \
  --pods "cloudtak=${work}/pods-cloudtak.json" \
  --workload "statefulset/takserver-ignite=${work}/ignite.json" \
  --workload "deployment/takserver-plugins=${work}/plugins.json" \
  --workload "deployment/takserver-config=${work}/config.json" \
  | tee -a "${top_file}"

echo "Wrote ${top_file}"
