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
uds run deploy-slim-core --no-progress
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
pvc_snapshot() {
  local claims claim
  claims="$(k get pod -n takserver "$(postgres_pod)" -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}')"
  test -n "${claims}"
  for claim in ${claims}; do
    k get pvc -n takserver "${claim}" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{" "}{.spec.volumeName}{"\n"}'
  done | sort
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
echo "PASS seeded PostgreSQL row on the released deployment"

# Only now create and deploy the PR package. Do not recreate identities or seed data.
uds run create-dev-package --set FLAVOR=upstream --no-progress
uds run create:test-bundle --set FLAVOR=upstream --no-progress
uds run deploy:test-bundle --no-progress --with options=--force-conflicts
health
pvc_snapshot > "${work}/postgres-pvc.after"
diff -u "${work}/postgres-pvc.before" "${work}/postgres-pvc.after"
actual="$(sql <<< 'SELECT marker || '\''|'\'' || created_at::text FROM upgrade_test.retained_state;')"
[[ "${actual}" = "${expected}" ]]
echo "PASS PostgreSQL row, creation timestamp, and persistent volume survived the upgrade"
sha256sum --check "${work}/certs.sha256"
gateway
stream
sso upgraded
sql <<< 'DROP SCHEMA upgrade_test CASCADE;'
echo "PASS released-to-PR upgrade: healthy TAK pods, SSO dashboard, retained client certificate, and PostgreSQL data"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "Upgrade baseline: ${tag} (${package})"
    echo "PASS: healthy TAK pods, fresh SSO dashboard login, retained 8089 client certificate, PostgreSQL row and PVC continuity."
  } >> "${GITHUB_STEP_SUMMARY}"
fi
