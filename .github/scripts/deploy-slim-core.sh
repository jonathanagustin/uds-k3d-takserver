#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Deploy the slim UDS Core checkpoint. A tarball of this version in the cache
# directory skips the OCI pull. The first run pulls k3d-core-slim-dev.
#
# The pull comes from this repository's GHCR mirror of the checkpoint
# (.github/workflows/mirror-checkpoint.yaml copies it byte for byte, so the
# digest is the upstream one). When the mirror does not have the version,
# the pull falls back to the upstream Defense Unicorns registry.
#
#   SLIM_CORE_MIRROR=""   pull from upstream only
#   SLIM_K3D_EXTRA_ARGS   k3d arguments for the checkpoint's K3D_EXTRA_ARGS.
#                         Defaults to the CI setting below on a CI runner and
#                         to nothing elsewhere.
set -euo pipefail

# renovate: datasource=github-tags depName=defenseunicorns/uds-core versioning=semver
slim_core_version=1.16.0
# Index digest of each checkpoint version, checked before a pull. A version
# without an entry (a fresh Renovate bump) is pulled by tag with a warning;
# the mirror workflow prints the line to add here.
# 1.15.x are the upgrade-test baselines (tasks.yaml, tests/upgrade.sh).
declare -A slim_core_digests=(
  [1.15.0]=sha256:c1ec81725e623a926e5d13b4dc165d93ca4737267853470d60cb8f3e47009d9c
  [1.15.2]=sha256:28a50932b6924683148615d88a9a475c3e03367df1378342ee4419d2610d2237
  [1.16.0]=sha256:d47b4ef370fd0e1ca2d5976fb1bedc7132178784e9b7453b28ff228509bb1d51
)
version="${SLIM_CORE_VERSION:-${slim_core_version}}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
out="${SLIM_PACKAGE_DIR:-${root}/.cache/k3d-core-slim-dev}"
upstream_repo="ghcr.io/defenseunicorns/dev/uds/checkpoints"
mirror_repo="${SLIM_CORE_MIRROR-ghcr.io/jonathanagustin/uds-k3d-takserver/checkpoints}"
want_digest="${slim_core_digests[${version}]:-}"

mkdir -p "${out}"
# uds bundles zarf and does not leave ./zarf in the repo until a zarf
# command has already run. `uds zarf` is that command.
if [[ -x "${root}/zarf" ]]; then
  zarf=("${root}/zarf")
elif command -v zarf >/dev/null 2>&1; then
  zarf=(zarf)
elif command -v uds >/dev/null 2>&1; then
  zarf=(uds zarf)
else
  echo "zarf is not available. Run this from uds so the CLI is present." >&2
  exit 1
fi

shopt -s nullglob
# The version is part of the name. An older tarball in the same directory
# must not be deployed in its place.
files=("${out}"/zarf-package-k3d-core-slim-dev-*-"${version}".tar.zst)
# Pull from repo $1 when its tag has the pinned digest (or no digest is
# pinned). Returns 1 without pulling otherwise.
pull_from() {
  local ref="$1/k3d-core-slim-dev:${version}" digest
  if ! digest="$("${zarf[@]}" tools registry digest "${ref}" 2>/dev/null)"; then
    echo "${ref} is not available"
    return 1
  fi
  if [[ -n "${want_digest}" && "${digest}" != "${want_digest}" ]]; then
    echo "::warning::${ref} is ${digest}, not the pinned ${want_digest}"
    return 1
  fi
  [[ -n "${want_digest}" ]] || echo "::warning::No digest pinned for k3d-core-slim-dev ${version} in $0; pulling ${ref} (${digest}) by tag"
  echo "Pulling oci://${ref} (${digest})"
  "${zarf[@]}" package pull "oci://${ref}" --output-directory "${out}"
}

if [[ "${#files[@]}" -eq 0 ]]; then
  if [[ -z "${mirror_repo}" ]] || ! pull_from "${mirror_repo}"; then
    pull_from "${upstream_repo}"
  fi
  files=("${out}"/zarf-package-k3d-core-slim-dev-*-"${version}".tar.zst)
fi
shopt -u nullglob

if [[ "${#files[@]}" -eq 0 ]]; then
  echo "No k3d-core-slim-dev ${version} package in ${out}" >&2
  exit 1
fi
if [[ "${#files[@]}" -gt 1 ]]; then
  echo "More than one k3d-core-slim-dev ${version} package in ${out}:" >&2
  printf '  %s\n' "${files[@]}" >&2
  exit 1
fi

# On a CI runner, turn off the API server's datastore compaction. k3s keeps
# the cluster in SQLite (kine), and kine exits with "Transaction commit
# failed" when a compaction transaction outlives its 5s timeout. On a busy
# runner disk that happened about every other run, and the k3s restart takes
# the API server and the registry down mid-deploy. A CI cluster lives about
# an hour, so the uncompacted history stays small. A long-lived local cluster
# keeps the default 5m interval.
extra="${SLIM_K3D_EXTRA_ARGS-}"
if [[ -z "${SLIM_K3D_EXTRA_ARGS+x}" && ( "${GITHUB_ACTIONS:-}" == "true" || "${CI:-}" == "true" ) ]]; then
  extra="--k3s-arg=--kube-apiserver-arg=etcd-compaction-interval=0@server:*"
fi

echo "Deploying ${files[0]}"
if [[ -n "${extra}" ]]; then
  echo "K3D_EXTRA_ARGS=${extra}"
  "${zarf[@]}" package deploy "${files[0]}" --confirm --features values=true --set "K3D_EXTRA_ARGS=${extra}"
else
  "${zarf[@]}" package deploy "${files[0]}" --confirm --features values=true
fi
if [[ -n "${extra}" ]] && command -v docker >/dev/null 2>&1; then
  server="$(docker ps --filter name=k3d- --filter name=server-0 --format '{{.Names}}')"
  if [[ -n "${server}" ]]; then
    echo "${server} k3s arguments:"
    docker inspect "${server}" --format '{{join .Args " "}}' || true
  fi
fi
