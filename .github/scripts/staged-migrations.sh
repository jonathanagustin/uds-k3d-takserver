#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# Manual workflow only. Never called by ordinary Test/Package/Full Core.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "${root}"
case "${SCENARIO:?}" in
  velero | identities | all) ;;
  *) exit 1 ;;
esac
identity_method="${IDENTITY_METHOD:-manual}"
case "${identity_method}" in manual | package | combined) ;; *) exit 1 ;; esac
if [[ "${identity_method}" != manual ]]; then
  [[ "${SCENARIO}" == identities ]]
  # Help/flag capability check only: before any cluster or package deployment.
  python3 tests/workload-identities/package_roundtrip.py preflight \
    --evidence "${RUNNER_TEMP:?}/staged-migrations/package-identity/journal.json"
fi
trial="${RUNNER_TEMP:?}/staged-migrations"
[[ ! -e "${trial}" ]]
mkdir -m 700 "${trial}"
if [[ "${SCENARIO}" != velero ]]; then
  # Fail cheaply before creating a cluster if the reviewed identity slice is absent.
  [[ -f tests/workload-identities/drive.py && -f tests/workload-identities/ProtocolProbe.java ]]
fi
# No builds or wait-for-future-package fallback in this bounded pilot.
[[ "$(./.github/scripts/dev-package.sh prebuilt)" == true ]]
case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64) arch=arm64 ;;
  *) exit 1 ;;
esac
flavored="zarf-package-takserver-${arch}-dev-upstream.tar.zst"
plain="zarf-package-takserver-${arch}-dev.tar.zst"
[[ -f "${flavored}" && ! -L "${flavored}" ]]
if [[ -e "${plain}" ]]; then
  cmp -- "${flavored}" "${plain}"
else
  cp -- "${flavored}" "${plain}"
fi
python3 tests/ephemeral-cluster.py bootstrap --context k3d-uds
SLIM_CORE_VERSION=1.16.0 ./.github/scripts/deploy-slim-core.sh
python3 tests/ephemeral-cluster.py mark --context k3d-uds
python3 tests/ephemeral-cluster.py verify --context k3d-uds
uds run fit-runner --no-progress
python3 tests/ephemeral-cluster.py verify --context k3d-uds
./tests/local-path-local.sh
# Optional diagnostics cannot turn missing health/acceptance evidence green.
watch_pid=""
if [[ "${PASSIVE_WATCH:-false}" == true ]]; then
  python3 tests/upgrade-agent-watch.py --enable-ephemeral-trial --context k3d-uds --seconds 900 \
    > "${trial}/passive-watch.jsonl" &
  watch_pid=$!
fi
cleanup_watch() {
  if [[ -n "${watch_pid}" ]]; then
    kill "${watch_pid}" 2>/dev/null || true
    wait "${watch_pid}" 2>/dev/null || true
  fi
}
trap cleanup_watch EXIT
helm template takserver charts/takserver --namespace takserver \
  --set-string backup.filesystem.enabled=true --show-only templates/filesystem-backup.yaml \
  > "${trial}/agent-resources.yaml"
python3 - "${trial}" <<'PY'
import pathlib,sys,yaml
root=pathlib.Path(sys.argv[1])
docs=[obj for obj in yaml.safe_load_all((root/'agent-resources.yaml').read_text()) if obj and obj.get('kind')=='Exemption']
assert len(docs)==1
(root/'exemption.yaml').write_text(yaml.safe_dump(docs[0]))
PY
python3 tests/velero-ownership/candidate.py prepare --exemption "${trial}/exemption.yaml" --directory "${trial}/candidate"
for variant in core detach clean; do
  timeout --kill-after=10s 1200 uds create "${trial}/candidate/${variant}" --confirm \
    --output "${trial}/candidate/${variant}" --no-progress --no-log-file
done
python3 tests/velero-ownership/candidate.py bind --directory "${trial}/candidate"
# The trusted pin helper changes the task default only for package creation.
# Deployment now uses the bound archives and copied pinned config; later tasks
# only prepare the API user/gateway. Restore exactly reviewed helper bytes.
python3 .github/scripts/staged-migrations.py restore-task-default --directory "${trial}/candidate"
if [[ "${SCENARIO}" == identities ]]; then
  python3 tests/velero-ownership/drive.py local-baseline --plan "${trial}/candidate/plan.json" --evidence "${trial}/baseline"
else
  timeout --kill-after=10s 10800 python3 tests/velero-ownership/drive.py round-trip --plan "${trial}/candidate/plan.json" --evidence "${trial}/owner"
fi
if [[ "${SCENARIO}" != velero ]]; then
  if [[ "${identity_method}" == manual || "${identity_method}" == combined ]]; then
    mkdir -m 700 "${trial}/identity"
    timeout --kill-after=10s 2700 python3 tests/workload-identities/drive.py round-trip --evidence "${trial}/identity/journal.json" --candidate-plan "${trial}/candidate/plan.json"
  fi
  if [[ "${identity_method}" == package || "${identity_method}" == combined ]]; then
    mkdir -m 700 "${trial}/package-identity"
    fresh=()
    if [[ "${FRESH_STRICT:-false}" == true ]]; then fresh+=(--fresh-strict); fi
    timeout --kill-after=10s 7500 python3 tests/workload-identities/package_roundtrip.py round-trip \
      --archive "${root}/${flavored}" --archive-sha256 "$(sha256sum "${flavored}" | cut -d ' ' -f 1)" \
      --candidate-plan "${trial}/candidate/plan.json" --evidence "${trial}/package-identity/journal.json" "${fresh[@]}"
  fi
fi
