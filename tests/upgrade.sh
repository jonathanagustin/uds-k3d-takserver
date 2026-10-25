#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Deploy the exact released package, seed state, then replace it with this PR.
set -euo pipefail
umask 077

baseline="${1:?Usage: upgrade.sh baseline.json}"
work="$(mktemp -d "${RUNNER_TEMP:-/tmp}/tak-upgrade.XXXXXX")"
trap 'rm -rf "${work}"' EXIT
root="$(pwd)"
export UDS_ARCH=amd64 FLAVOR=upstream
read_baseline() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "${baseline}" "$1"; }
tag="$(read_baseline tag)"
package="$(read_baseline package)"
version="$(read_baseline version)"

# Use the released bundle and test values, without checking out or executing old code.
git archive "${tag}" bundle values | tar -x -C "${work}"
export UPGRADE_PACKAGE_REF="${version}-upstream"
# Releases from v0.3.0 on are signed keylessly by release.yaml, and uds create
# refuses a signed package without the identity to verify it against.
export UPGRADE_SIGNER_REGEXP='^https://github\.com/jonathanagustin/uds-k3d-takserver/\.github/workflows/release\.yaml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/main)$'
uds zarf tools yq -i '
  (.packages[] | select(.name == "takserver") | .path) = "../" |
  (.packages[] | select(.name == "takserver") | .ref) = strenv(UPGRADE_PACKAGE_REF) |
  (.packages[] | select(.name == "takserver") | .keylessVerification) = {
    "certificateIdentityRegexp": strenv(UPGRADE_SIGNER_REGEXP),
    "certificateOIDCIssuer": "https://token.actions.githubusercontent.com"
  } |
  del(.packages[] | select(.name == "takserver") | .repository)
' "${work}/bundle/uds-bundle.yaml"
if ! uds zarf package pull "${package}" --architecture=amd64 --no-progress --features values=true -o "${work}"; then
  echo "::error title=Released package unavailable::Cannot pull ${package} for ${tag}. Publish this release's upstream amd64 package before rerunning."
  exit 1
fi
released="${work}/zarf-package-takserver-amd64-${version}-upstream.tar.zst"
test -s "${released}"
# A bundle that names a different signer must refuse the same signed package.
# Check the reason too, so a network or disk failure cannot pass for a refusal.
cp -r "${work}/bundle" "${work}/bundle-wrong-signer"
WRONG_SIGNER_REGEXP='^https://github\.com/not-this-repo/not-this-repo/\.github/workflows/release\.yaml@refs/heads/main$' \
  uds zarf tools yq -i '(.packages[] | select(.name == "takserver") | .keylessVerification.certificateIdentityRegexp) = strenv(WRONG_SIGNER_REGEXP)' \
  "${work}/bundle-wrong-signer/uds-bundle.yaml"
if wrong="$(uds create "${work}/bundle-wrong-signer" --architecture=amd64 --confirm --no-progress 2>&1)"; then
  echo "::error title=Wrong signer accepted::uds create accepted a bundle whose keylessVerification names a different signer."
  exit 1
fi
if ! grep -q 'failed to verify certificate identity' <<<"${wrong}"; then
  echo "${wrong}"
  echo "::error title=Wrong signer failed for another reason::uds create failed, but not on the certificate identity check."
  exit 1
fi
rm -rf "${work}/bundle-wrong-signer"
uds create "${work}/bundle" --architecture=amd64 --confirm --no-progress
# Release 0.6.0's admission chart asks for Pepr controller v2.0.3. The 1.15.2
# checkpoint only publishes v2.0.5, so the baseline cluster has to start from
# 1.15.0, which still has v2.0.3. The released bundle then deploys core 1.15.2
# and leaves v2.0.5 in the registry for this branch.
SLIM_CORE_VERSION=1.15.0 uds run deploy-slim-core --no-progress
uds run fit-runner --no-progress
mapfile -t bundles < <(find "${work}/bundle" -maxdepth 1 -name 'uds-bundle-*.tar.zst')
[[ "${#bundles[@]}" -eq 1 ]]
UDS_CONFIG="${work}/bundle/uds-config.yaml" uds deploy "${bundles[0]}" --confirm --no-progress --force-conflicts

k() { uds zarf tools kubectl "$@"; }
health() { uds run test:health-check --no-progress; }
gateway() { uds run test:gateway --no-progress; }
stream() {
  python3 -B tests/upgrade-stream.py --port "$(cat /tmp/tak-gateway-port)" \
    --cert "${work}/certs/admin.pem" --key "${work}/certs/admin.key"
}
postgres_pod() {
  k get pods -n takserver -l app.kubernetes.io/name=postgresql -o json | python3 -c '
import json,sys
pods = [p for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")]
assert len(pods) == 1, "expected one PostgreSQL pod"
print(pods[0]["metadata"]["name"])
'
}
sql() {
  k exec -i -n takserver "$(postgres_pod)" -c postgresql -- \
    psql -X -w -U postgres -d cot -v ON_ERROR_STOP=1 -At
}
cloudtak_pod() {
  k get pods -n cloudtak -l app=cloudtak-postgis -o json | python3 -c '
import json,sys
pods = [p for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")]
assert len(pods) == 1, "expected one CloudTAK PostGIS pod"
print(pods[0]["metadata"]["name"])
'
}
cloudtak_sql() {
  # The single quotes are the script that runs inside the pod.
  # shellcheck disable=SC2016
  k exec -i -n cloudtak "$(cloudtak_pod)" -c postgis -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'
}
pvc_snapshot() {
  local ns="${1:-takserver}"
  local pod="${2:-}"
  local claims claim
  if [[ -z "${pod}" ]]; then
    pod="$(postgres_pod)"
  fi
  claims="$(k get pod -n "${ns}" "${pod}" -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}')"
  test -n "${claims}"
  for claim in ${claims}; do
    k get pvc -n "${ns}" "${claim}" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{" "}{.spec.volumeName}{"\n"}'
  done | sort
}
require_pg() {
  local label="$1" version="$2" extension="$3" low="$4" high="$5" prefix="$6"
  # ${extension#prefix.} is the suffix after "3.4." or "3.6.". An unchanged
  # value means the extension is not that PostGIS release.
  local rest="${extension#"${prefix}."}"
  if [[ ! "${version}" =~ ^[0-9]+$ || "${version}" -lt "${low}" || "${version}" -ge "${high}" || "${rest}" == "${extension}" || -z "${rest}" ]]; then
    echo "${label}: expected PostgreSQL ${low} and PostGIS ${prefix}, got ${version:-unset} / ${extension:-unset}" >&2
    exit 1
  fi
}
require_upgrade_log() {
  local ns="$1" pod="$2" container="$3" logs
  logs="$(k logs -n "${ns}" "${pod}" -c "${container}" 2>/dev/null || true)"
  if grep -F -q 'upgrading PostgreSQL 15' <<<"${logs}"; then
    return 0
  fi
  logs="$(k logs -n "${ns}" "${pod}" -c "${container}" --previous 2>/dev/null || true)"
  if grep -F -q 'upgrading PostgreSQL 15' <<<"${logs}"; then
    return 0
  fi
  echo "pod ${ns}/${pod} did not log an in-place PostgreSQL 15 upgrade" >&2
  k logs -n "${ns}" "${pod}" -c "${container}" --tail=80 >&2 || true
  exit 1
}
sso() {
  local phase="$1"
  # No reachability-based skip and no reused session: each phase signs in afresh.
  docker run --rm --network=host --shm-size=1g --security-opt seccomp=unconfined \
    --user "$(id -u):$(id -g)" \
    -e CI=true -e UPGRADE_TEST=1 -e SKIP_SSO_SETUP=0 \
    -e TAK_SSO_URL=https://takserver.uds.dev/ \
    -e KEYCLOAK_USER="${KEYCLOAK_USER:-doug}" \
    -e KEYCLOAK_PASSWORD="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}" \
    -e PLAYWRIGHT_HTML_OUTPUT_DIR=".playwright/reports/upgrade-${phase}" \
    -v "${root}/tests:/app" -w /app mcr.microsoft.com/playwright:v1.64.1 \
    bash -lc 'export HOME=/tmp COREPACK_HOME=/tmp/corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0 && mkdir -p "$COREPACK_HOME" && corepack prepare pnpm@10.33.4 --activate && corepack pnpm install --frozen-lockfile && corepack pnpm exec playwright test upgrade-sso.spec.ts --project=chromium --no-deps'
}

health
uds run setup:keycloak-user --no-progress --with group="/UDS Core/Admin"
python3 -B tests/ensure-tak-group.py
gateway
# The fresh directory is extracted only here, before the upgrade.
bash tests/extract-certs.sh "${work}/certs"
sha256sum "${work}/certs/admin.pem" "${work}/certs/admin.key" > "${work}/certs.sha256"
stream
sso baseline

marker="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
sql <<SQL
CREATE SCHEMA upgrade_test;
CREATE TABLE upgrade_test.retained_state (marker text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO upgrade_test.retained_state (marker) VALUES ('${marker}');
SQL
expected="$(sql <<< 'SELECT marker || '\''|'\'' || created_at::text FROM upgrade_test.retained_state;')"
[[ "${expected}" == "${marker}|"* ]]
pvc_snapshot > "${work}/postgres-pvc.before"
released_version="$(sql <<< 'SHOW server_version_num;')"
released_postgis="$(sql <<< 'SELECT extversion FROM pg_extension WHERE extname = '\''postgis'\'';')"
require_pg "released TAK database" "${released_version}" "${released_postgis}" 150000 160000 3.4
echo "PASS released TAK database is PostgreSQL ${released_version} / PostGIS ${released_postgis}"

if ! k get statefulset cloudtak-postgis -n cloudtak >/dev/null 2>&1; then
  echo "released deployment has no CloudTAK PostGIS statefulset" >&2
  exit 1
fi
k rollout status statefulset/cloudtak-postgis -n cloudtak --timeout=600s
cloudtak_marker="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
cloudtak_sql <<SQL
CREATE TABLE upgrade_test_retained (marker text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO upgrade_test_retained (marker) VALUES ('${cloudtak_marker}');
SQL
cloudtak_expected="$(cloudtak_sql <<< 'SELECT marker || '\''|'\'' || created_at::text FROM upgrade_test_retained;')"
[[ "${cloudtak_expected}" == "${cloudtak_marker}|"* ]]
released_cloudtak_version="$(cloudtak_sql <<< 'SHOW server_version_num;')"
released_cloudtak_postgis="$(cloudtak_sql <<< 'SELECT extversion FROM pg_extension WHERE extname = '\''postgis'\'';')"
require_pg "released CloudTAK database" "${released_cloudtak_version}" "${released_cloudtak_postgis}" 150000 160000 3.4
pvc_snapshot cloudtak "$(cloudtak_pod)" > "${work}/cloudtak-pvc.before"
echo "PASS released CloudTAK database is PostgreSQL ${released_cloudtak_version} / PostGIS ${released_cloudtak_postgis}"

# Only now create and deploy the PR package. Do not recreate identities or seed data.
uds run create-dev-package --set FLAVOR=upstream --no-progress
uds run create:test-bundle --set FLAVOR=upstream --no-progress
uds run deploy:test-bundle --no-progress --with options=--force-conflicts
health
mode="$(k get secret takserver-keystore -n takserver -o jsonpath='{.metadata.annotations.uds\.dev/keystore-password}')"
legacy="$(k get secret takserver-keystore -n takserver -o jsonpath='{.data.CAPASS}' | base64 -d)"
if [[ "${mode}" != "legacy" || "${legacy}" != "atakatak" ]]; then
  echo "upgrade from a release that used the example keystore password did not keep it (mode ${mode:-unset})" >&2
  exit 1
fi
unset legacy
echo "PASS upgrade kept the keystore password those certificates were issued with"
pvc_snapshot > "${work}/postgres-pvc.after"
diff -u "${work}/postgres-pvc.before" "${work}/postgres-pvc.after"
actual="$(sql <<< 'SELECT marker || '\''|'\'' || created_at::text FROM upgrade_test.retained_state;')"
[[ "${actual}" = "${expected}" ]]
server_version="$(sql <<< 'SHOW server_version_num;')"
postgis_version="$(sql <<< 'SELECT extversion FROM pg_extension WHERE extname = '\''postgis'\'';')"
require_pg "upgraded TAK database" "${server_version}" "${postgis_version}" 180000 190000 3.6
require_upgrade_log takserver "$(postgres_pod)" postgresql
echo "PASS TAK PostgreSQL ${released_version} moved to ${server_version} / PostGIS ${postgis_version} on the same volume"

k rollout status statefulset/cloudtak-postgis -n cloudtak --timeout=600s
cloudtak_actual="$(cloudtak_sql <<< 'SELECT marker || '\''|'\'' || created_at::text FROM upgrade_test_retained;')"
[[ "${cloudtak_actual}" = "${cloudtak_expected}" ]]
pvc_snapshot cloudtak "$(cloudtak_pod)" > "${work}/cloudtak-pvc.after"
diff -u "${work}/cloudtak-pvc.before" "${work}/cloudtak-pvc.after"
cloudtak_version="$(cloudtak_sql <<< 'SHOW server_version_num;')"
cloudtak_postgis="$(cloudtak_sql <<< 'SELECT extversion FROM pg_extension WHERE extname = '\''postgis'\'';')"
require_pg "upgraded CloudTAK database" "${cloudtak_version}" "${cloudtak_postgis}" 180000 190000 3.6
require_upgrade_log cloudtak "$(cloudtak_pod)" postgis
cloudtak_sql <<< 'DROP TABLE upgrade_test_retained;'
echo "PASS CloudTAK PostgreSQL ${released_cloudtak_version} moved to ${cloudtak_version} / PostGIS ${cloudtak_postgis} on the same volume"
sha256sum --check "${work}/certs.sha256"
gateway
stream
sso upgraded
sql <<< 'DROP SCHEMA upgrade_test CASCADE;'
echo "PASS released-to-PR upgrade: healthy TAK pods, SSO dashboard, retained client certificate, and PostgreSQL data"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "Upgrade baseline: ${tag} (${package})"
    echo "PASS: healthy TAK pods, fresh SSO dashboard login, retained 8089 client certificate, and in-place PostgreSQL 15 to 18 on the TAK and CloudTAK volumes."
  } >> "${GITHUB_STEP_SUMMARY}"
fi
