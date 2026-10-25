#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Backup the takserver and cloudtak namespaces with Velero, delete them, restore
# them, and load the logical dumps back. Volumes are not in the backup
# (adr/0016-logical-db-dump.md). The client certificate used after the restore
# is the one copied out before the delete.
#
# Skips when the Velero Backup CRD is absent, which is the slim bundle.
# Deletes both namespaces. test:full-core runs this last.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${root}"

log="out/backup-restore.txt"
mkdir -p out
: > "${log}"

say() {
  printf '%s\n' "$*" | tee -a "${log}"
}

k() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

if ! k api-resources --api-group=velero.io 2>/dev/null | grep -q '^backups '; then
  say "velero.io Backup is not installed; backup-restore skipped"
  exit 0
fi

run_id="${GITHUB_RUN_ID:-}"
if [[ -z "${run_id}" ]]; then
  run_id="$(date +%s)"
fi
attempt="${GITHUB_RUN_ATTEMPT:-1}"
run_id="$(printf '%s' "${run_id}" | tr -cd 'a-zA-Z0-9')"
attempt="$(printf '%s' "${attempt}" | tr -cd '0-9')"
note="run-${run_id}-${attempt}"
backup_name="tak-ci-${run_id}-${attempt}"
restore_name="${backup_name}-r"

work="$(mktemp -d)"
cleanup() {
  rm -rf "${work}"
}
trap cleanup EXIT

# A Secret is about 1Mi. Base64 and metadata need room under that.
max_dump_bytes=700000

pod_name() {
  local ns="$1"
  local selector="$2"
  local fallback="$3"
  local name
  name="$(k get pod -n "${ns}" -l "${selector}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "${name}" ]]; then
    name="${fallback}"
  fi
  printf '%s\n' "${name}"
}

container_name() {
  local ns="$1"
  local pod="$2"
  k get pod -n "${ns}" "${pod}" -o jsonpath='{.spec.containers[0].name}'
}

# pg_dump or psql inside a pod that already has POSTGRES_PASSWORD, or none.
# The password stays in the pod. Stdout is the SQL or the query result.
in_pod() {
  local ns="$1"
  local pod="$2"
  local container="$3"
  shift 3
  # The single quotes are the script that runs inside the pod.
  # shellcheck disable=SC2016
  k exec -n "${ns}" "${pod}" -c "${container}" -- sh -c '
    if [ -n "${POSTGRES_PASSWORD:-}" ]; then
      export PGPASSWORD="${POSTGRES_PASSWORD}"
    fi
    exec "$@"
  ' sh "$@"
}

write_marker() {
  local ns="$1"
  local pod="$2"
  local container="$3"
  local user="$4"
  local db="$5"
  say "marker ${ns}/${db} ${note}"
  in_pod "${ns}" "${pod}" "${container}" \
    psql -h 127.0.0.1 -U "${user}" -d "${db}" -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE IF NOT EXISTS uds_restore_marker (id text PRIMARY KEY, note text NOT NULL);" \
    -c "INSERT INTO uds_restore_marker (id, note) VALUES ('velero-restore-test', '${note}') ON CONFLICT (id) DO UPDATE SET note = EXCLUDED.note;"
}

read_marker() {
  local ns="$1"
  local pod="$2"
  local container="$3"
  local user="$4"
  local db="$5"
  in_pod "${ns}" "${pod}" "${container}" \
    psql -h 127.0.0.1 -U "${user}" -d "${db}" -tAc \
    "SELECT note FROM uds_restore_marker WHERE id = 'velero-restore-test'"
}

dump_db() {
  local ns="$1"
  local pod="$2"
  local container="$3"
  local user="$4"
  local db="$5"
  local dest="$6"
  say "pg_dump ${ns}/${db}"
  in_pod "${ns}" "${pod}" "${container}" \
    pg_dump -h 127.0.0.1 -U "${user}" -d "${db}" --no-owner --no-acl > "${dest}"
  local bytes
  bytes="$(wc -c < "${dest}" | tr -d ' ')"
  say "pg_dump ${ns}/${db} ${bytes} bytes"
  if [[ "${bytes}" -gt "${max_dump_bytes}" ]]; then
    say "dump is ${bytes} bytes, over ${max_dump_bytes}; a Secret cannot hold it" >&2
    exit 1
  fi
  if ! grep -q 'uds_restore_marker' "${dest}"; then
    say "dump of ${ns}/${db} has no marker table" >&2
    exit 1
  fi
}

store_secret() {
  local ns="$1"
  local name="$2"
  local file="$3"
  # Server-side apply: client-side apply copies the whole Secret into the
  # last-applied annotation, which is capped at 256KiB.
  k create secret generic "${name}" -n "${ns}" \
    --from-file=dump.sql="${file}" \
    --dry-run=client -o yaml | k apply --server-side --force-conflicts -f -
  say "Secret ${ns}/${name} stored"
}

wait_phase() {
  local kind="$1"
  local name="$2"
  local tries="$3"
  local phase
  local _
  for _ in $(seq 1 "${tries}"); do
    phase="$(k get "${kind}" -n velero "${name}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    say "${kind} ${name} phase=${phase:-empty}"
    case "${phase}" in
      Completed)
        return 0
        ;;
      Failed | FailedValidation | PartiallyFailed)
        k describe "${kind}" -n velero "${name}" >&2 || true
        return 1
        ;;
      *) ;;
    esac
    sleep 10
  done
  say "${kind} ${name} was not Completed" >&2
  k describe "${kind}" -n velero "${name}" >&2 || true
  return 1
}

say "backup-restore ${backup_name} marker ${note}"

if k get deploy minio -n uds-dev-stack >/dev/null 2>&1; then
  say "scale MinIO to 1; fit-runner had set it to 0, and Velero's bucket is there"
  k scale deploy/minio -n uds-dev-stack --replicas=1
  if ! k rollout status deploy/minio -n uds-dev-stack --timeout=180s; then
    k get pods -n uds-dev-stack -o wide >&2 || true
    exit 1
  fi
else
  say "Deployment uds-dev-stack/minio is missing; Velero's default bucket has nowhere to go" >&2
  exit 1
fi

# The dev stack gives Velero and Loki one bucket, and Loki writes its chunks
# under fake/ there. Velero marks a bucket Unavailable when it holds a
# top-level directory it does not own, so keep Velero under its own prefix.
k patch backupstoragelocations.velero.io default -n velero --type merge \
  -p '{"spec":{"objectStorage":{"prefix":"velero"}}}'

bsl_ok=0
for _ in $(seq 1 30); do
  phase="$(k get backupstoragelocations.velero.io default -n velero -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  say "BackupStorageLocation default phase=${phase:-empty}"
  if [[ "${phase}" == "Available" ]]; then
    bsl_ok=1
    break
  fi
  sleep 10
done
if [[ "${bsl_ok}" -ne 1 ]]; then
  k describe backupstoragelocations.velero.io default -n velero >&2 || true
  exit 1
fi

tak_pod="$(pod_name takserver app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary takserver-postgresql-0)"
tak_container="$(container_name takserver "${tak_pod}")"
ct_pod="$(pod_name cloudtak app=cloudtak-postgis cloudtak-postgis-0)"
ct_container="$(container_name cloudtak "${ct_pod}")"
say "tak postgres ${tak_pod}/${tak_container}"
say "cloudtak postgres ${ct_pod}/${ct_container}"

write_marker takserver "${tak_pod}" "${tak_container}" postgres cot
write_marker cloudtak "${ct_pod}" "${ct_container}" cloudtak cloudtak
dump_db takserver "${tak_pod}" "${tak_container}" postgres cot "${work}/tak.sql"
dump_db cloudtak "${ct_pod}" "${ct_container}" cloudtak cloudtak "${work}/cloudtak.sql"
store_secret takserver tak-db-dump "${work}/tak.sql"
store_secret cloudtak cloudtak-db-dump "${work}/cloudtak.sql"

cert_dir="$(./tests/extract-certs.sh /tmp/tak-certs-before-restore)"
say "client certificate copied to ${cert_dir} before the backup"

cat <<EOF | k apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: ${backup_name}
  namespace: velero
  labels:
    app.kubernetes.io/part-of: tak-backup
spec:
  includedNamespaces:
    - takserver
    - cloudtak
  includeClusterResources: false
  snapshotVolumes: false
  ttl: 2h0m0s
EOF

wait_phase backup.velero.io "${backup_name}" 60
say "Backup ${backup_name} Completed"

say "delete namespaces takserver and cloudtak"
k delete namespace takserver cloudtak --wait=true --timeout=600s

cat <<EOF | k apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: ${restore_name}
  namespace: velero
  labels:
    app.kubernetes.io/part-of: tak-backup
spec:
  backupName: ${backup_name}
  includedNamespaces:
    - takserver
    - cloudtak
  includeClusterResources: false
EOF

wait_phase restore.velero.io "${restore_name}" 60
say "Restore ${restore_name} Completed"

apps_up=0
for _ in $(seq 1 60); do
  if k get deploy takserver-api -n takserver >/dev/null 2>&1 \
    && k get deploy cloudtak -n cloudtak >/dev/null 2>&1 \
    && k get secret tak-db-dump -n takserver >/dev/null 2>&1 \
    && k get secret cloudtak-db-dump -n cloudtak >/dev/null 2>&1 \
    && k get configmap cert-migration -n takserver >/dev/null 2>&1; then
    apps_up=1
    break
  fi
  sleep 5
done
if [[ "${apps_up}" -ne 1 ]]; then
  say "restored namespaces are missing the API, CloudTAK, a dump Secret, or cert-migration" >&2
  k get deploy,secret,configmap -n takserver >&2 || true
  k get deploy,secret -n cloudtak >&2 || true
  exit 1
fi
say "restored Secrets tak-db-dump and cloudtak-db-dump and ConfigMap cert-migration"

for name in takserver-api takserver-messaging takserver-plugins takserver-config; do
  k scale "deploy/${name}" -n takserver --replicas=0
done
k scale deploy/cloudtak -n cloudtak --replicas=0

k wait --for=condition=ready pod -n takserver -l app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary --timeout=300s
k wait --for=condition=ready pod -n cloudtak -l app=cloudtak-postgis --timeout=300s

tak_pod="$(pod_name takserver app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary takserver-postgresql-0)"
tak_container="$(container_name takserver "${tak_pod}")"
ct_pod="$(pod_name cloudtak app=cloudtak-postgis cloudtak-postgis-0)"
ct_container="$(container_name cloudtak "${ct_pod}")"

reload_db() {
  local ns="$1"
  local pod="$2"
  local container="$3"
  local user="$4"
  local db="$5"
  local file="$6"
  say "reload ${ns}/${db}"
  in_pod "${ns}" "${pod}" "${container}" \
    psql -h 127.0.0.1 -U "${user}" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${db} WITH (FORCE);" \
    -c "CREATE DATABASE ${db};"
  # shellcheck disable=SC2016
  k exec -i -n "${ns}" "${pod}" -c "${container}" -- sh -c '
    if [ -n "${POSTGRES_PASSWORD:-}" ]; then
      export PGPASSWORD="${POSTGRES_PASSWORD}"
    fi
    exec psql -h 127.0.0.1 -U "$1" -d "$2" -v ON_ERROR_STOP=1
  ' sh "${user}" "${db}" < "${file}"
}

reload_db takserver "${tak_pod}" "${tak_container}" postgres cot "${work}/tak.sql"
reload_db cloudtak "${ct_pod}" "${ct_container}" cloudtak cloudtak "${work}/cloudtak.sql"

tak_note="$(read_marker takserver "${tak_pod}" "${tak_container}" postgres cot | tr -d '[:space:]')"
ct_note="$(read_marker cloudtak "${ct_pod}" "${ct_container}" cloudtak cloudtak | tr -d '[:space:]')"
say "marker takserver ${tak_note}"
say "marker cloudtak ${ct_note}"
if [[ "${tak_note}" != "${note}" || "${ct_note}" != "${note}" ]]; then
  say "marker read back does not match ${note}" >&2
  exit 1
fi
say "marker ${note} read back from both databases"

for name in takserver-api takserver-messaging takserver-plugins takserver-config; do
  k scale "deploy/${name}" -n takserver --replicas=1
  k rollout status "deploy/${name}" -n takserver --timeout=600s
done
k scale deploy/cloudtak -n cloudtak --replicas=1
k rollout status deploy/cloudtak -n cloudtak --timeout=600s

say "api-smoke with the client certificate issued before the backup"
TAK_CLIENT_CERT="${cert_dir}/admin.pem" \
  TAK_CLIENT_KEY="${cert_dir}/admin.key" \
  ./tests/api-smoke.sh

say "backup-restore passed"
