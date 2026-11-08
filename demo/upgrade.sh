#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The "Upgrades from the Last Signed Release" chapter of the Operate and
# Trust video. It runs last in the Demo Video workflow, after every other
# chapter, because it replaces the demo cluster.
#
#   demo/upgrade.sh prepare   not recorded: builds the previous release's
#                             bundle from its signed package, then a new
#                             k3d-core-slim-dev cluster
#   demo/upgrade.sh record    recorded with asciinema, split at the prompts
#                             by demo/render-cast.py:
#     1. verify the previous release package's signature
#     2. deploy that release
#     3. note TAK's CA, a row written to TAK's database, and its volume
#     4. upgrade in place to this run's bundle
#     5. the same CA, row and volume after the upgrade
#
# It follows tests/upgrade.sh, the upgrade test CI runs on every pull request.
# UPGRADE_FROM picks the previous release (default: the newest vX.Y.Z tag
# below DEMO_VERSION). The new bundle is the one demo/deploy.sh built.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
phase="${1:?usage: demo/upgrade.sh prepare|record}"
work="${DEMO_UPGRADE_DIR:-/tmp/demo-upgrade}"
arch=amd64
current="${DEMO_VERSION:-$(python3 -c 'import json; print(json.load(open(".release-please-manifest.json"))["."])')}"
# The release workflow's keyless signing identity, as in demo/shell.sh.
RELEASE_WORKFLOW='^https://github\.com/jonathanagustin/(uds-k3d-takserver|uds-takserver)/\.github/workflows/release\.yaml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/main)$'
RELEASE_ISSUER=https://token.actions.githubusercontent.com
k() { uds zarf tools kubectl "$@"; }
prompt() { printf '\n\033[38;2;129;140;248muds-k3d-takserver\033[0m \033[38;2;203;213;225m$\033[0m %s\n' "$*"; }

previous_version() {
  if [[ -n "${UPGRADE_FROM:-}" ]]; then
    echo "${UPGRADE_FROM#v}"
    return
  fi
  git ls-remote --tags --refs origin 'v*' | sed -n 's|.*refs/tags/v\([0-9]*\.[0-9]*\.[0-9]*\)$|\1|p' |
    python3 -c 'import sys
cur = tuple(map(int, sys.argv[1].split(".")))
tags = sorted({tuple(map(int, t.split("."))) for t in sys.stdin.read().split()})
older = [t for t in tags if t < cur]
if not older:
    sys.exit("no release older than " + sys.argv[1])
print(".".join(map(str, older[-1])))' "${current}"
}

new_bundle() {
  local name version
  name="$(uds zarf tools yq -r .metadata.name bundle/uds-bundle.yaml)"
  version="$(uds zarf tools yq -r .metadata.version bundle/uds-bundle.yaml)"
  echo "bundle/uds-bundle-${name}-${arch}-${version}.tar.zst"
}

if [[ "${phase}" == prepare ]]; then
  previous="$(previous_version)"
  echo "Upgrade chapter: v${previous} to v${current}"
  test -s "$(new_bundle)"
  rm -rf "${work}"
  mkdir -p "${work}"
  echo "${previous}" > "${work}/previous"
  # The released bundle and values, without checking out or running old code.
  git fetch --no-tags --depth=1 origin "refs/tags/v${previous}:refs/tags/v${previous}"
  git archive "v${previous}" bundle values | tar -x -C "${work}"
  export UPGRADE_PACKAGE_REF="${previous}-upstream" UPGRADE_SIGNER_REGEXP="${RELEASE_WORKFLOW}"
  uds zarf tools yq -i '
    (.packages[] | select(.name == "takserver") | .path) = "../" |
    (.packages[] | select(.name == "takserver") | .ref) = strenv(UPGRADE_PACKAGE_REF) |
    (.packages[] | select(.name == "takserver") | .keylessVerification) = {
      "certificateIdentityRegexp": strenv(UPGRADE_SIGNER_REGEXP),
      "certificateOIDCIssuer": "https://token.actions.githubusercontent.com"
    } |
    del(.packages[] | select(.name == "takserver") | .repository)
  ' "${work}/bundle/uds-bundle.yaml"
  uds zarf package pull "oci://ghcr.io/jonathanagustin/uds-k3d-takserver/takserver:${previous}-upstream" \
    --architecture "${arch}" --certificate-identity-regexp "${RELEASE_WORKFLOW}" \
    --certificate-oidc-issuer "${RELEASE_ISSUER}" --features values=true -o "${work}" --no-progress
  uds create "${work}/bundle" --architecture "${arch}" --confirm --no-progress
  # A new cluster for the previous release. The demo cluster is no longer
  # needed: every other chapter is recorded by now.
  k3d cluster delete uds || true
  uds run deploy-slim-core --no-progress
  uds run fit-runner --no-progress
  exit 0
fi

previous="$(cat "${work}/previous")"
old_bundle="$(find "${work}/bundle" -maxdepth 1 -name 'uds-bundle-*.tar.zst' | head -n 1)"
old_package="zarf-package-takserver-${arch}-${previous}-upstream.tar.zst"
postgres_pod() {
  k get pods -n takserver -l app.kubernetes.io/name=postgresql -o json | python3 -c 'import json, sys
pods = [p for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")]
print(pods[0]["metadata"]["name"] if pods else "")'
}
sql() {
  k exec -i -n takserver "$(postgres_pod)" -c postgresql -- psql -X -w -U postgres -d cot -v ON_ERROR_STOP=1 -At
}
package_version() {
  uds zarf package list -o json 2>/dev/null | python3 -c 'import json, sys
def walk(node):
    if isinstance(node, dict):
        name = node.get("name") or node.get("package") or node.get("Package")
        if name == "takserver":
            for key in ("version", "Version"):
                if node.get(key):
                    return node[key]
        for value in node.values():
            found = walk(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = walk(value)
            if found:
                return found
print(walk(json.load(sys.stdin)) or "?")'
}
volumes() {
  local claim
  for claim in $(k get pod -n takserver "$(postgres_pod)" -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}'); do
    printf '%s %s ' "${claim}" "$(k get pvc -n takserver "${claim}" -o jsonpath='{.spec.volumeName}')"
  done
}
facts() {
  echo "TAK package:      $(package_version)"
  echo "TAK CA:           $(k get configmap cert-migration -n takserver -o jsonpath='{.binaryData.ca\.pem}' | base64 -d |
    openssl x509 -noout -subject -fingerprint -sha256 -nameopt oneline | tr '\n' ' ')"
  echo "keystore secret:  sha256 $(k get secret takserver-keystore -n takserver -o jsonpath='{.data}' | sha256sum | cut -c1-16) (value not shown)"
  echo "database row:     $(sql <<< 'SELECT note || '\'' at '\'' || created_at::text FROM demo_upgrade.kept;')"
  echo "PostgreSQL:       $(sql <<< 'SHOW server_version;')"
  echo "database volume:  $(volumes)"
}

# shellcheck disable=SC2016
prompt "uds zarf package verify ${old_package} --certificate-identity-regexp \$RELEASE_WORKFLOW --certificate-oidc-issuer \$RELEASE_ISSUER"
uds zarf package verify "${work}/${old_package}" --certificate-identity-regexp "${RELEASE_WORKFLOW}" \
  --certificate-oidc-issuer "${RELEASE_ISSUER}"

prompt "uds deploy $(basename "${old_bundle}") --confirm   # the last signed release, v${previous}"
UDS_CONFIG="${work}/bundle/uds-config.yaml" uds deploy "${old_bundle}" --confirm --no-progress --force-conflicts
uds run test:health-check --no-progress >/dev/null

prompt "# v${previous} is running. Write a row to TAK's database and note the CA, keystore and volume"
sql >/dev/null <<SQL
CREATE SCHEMA IF NOT EXISTS demo_upgrade;
CREATE TABLE IF NOT EXISTS demo_upgrade.kept (note text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO demo_upgrade.kept (note) VALUES ('written by v${previous}') ON CONFLICT DO NOTHING;
SQL
facts | tee "${work}/before.txt"

new="$(new_bundle)"
options=(--force-conflicts)
# Like tests/upgrade.sh: when core-base did not change, only TAK is upgraded.
core='.packages[] | select(.name == "core-base")'
if [[ "$(uds zarf tools yq -o json "${core}" "${work}/bundle/uds-bundle.yaml")" == \
  "$(uds zarf tools yq -o json "${core}" bundle/uds-bundle.yaml)" ]]; then
  options+=(--packages takserver)
fi
prompt "uds deploy $(basename "${new}") ${options[*]:1} --confirm   # upgrade in place to v${current}"
UDS_CONFIG=bundle/uds-config.yaml uds deploy "${new}" --confirm --no-progress "${options[@]}"
uds run test:health-check --no-progress >/dev/null

prompt "# After the upgrade: the same CA, keystore, row and volume"
facts | tee "${work}/after.txt"
# Everything but the package version and PostgreSQL version must match.
diff <(grep -v -e '^TAK package' -e '^PostgreSQL' "${work}/before.txt") \
  <(grep -v -e '^TAK package' -e '^PostgreSQL' "${work}/after.txt") && echo "kept: CA, keystore, database row and volume"
prompt ""
