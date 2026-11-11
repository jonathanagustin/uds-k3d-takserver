#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the dev Zarf package once per set of inputs and reuse it.
#
# The key hashes the working tree (after pin-image-tags.sh, so it covers the
# image tags too) of every tracked file that can go into the package, plus the
# UDS CLI version, the flavor and the architecture. DOMAIN and TAK_IMAGE_TAG
# are not in the key: their values come from tasks.yaml and the bundle files,
# which are hashed. A run that overrides them with --set must not reuse. The package is
# published as ghcr.io/jonathanagustin/uds-takserver/ci-packages/takserver:<key>,
# a tag written once by the run that built it and never overwritten.
#
#   dev-package.sh key        print the key
#   dev-package.sh prebuilt   print true after placing a published package with
#                             this key at the path create would write; false
#                             otherwise (the caller then creates it). Waits up
#                             to DEV_PACKAGE_WAIT_SECONDS (default 0) for a
#                             parallel job to publish it, and stops early
#                             once that Package run has finished.
#   dev-package.sh publish    publish the created package unless the tag exists
#
# KEY_SALT changes every key. DEV_PACKAGE_REUSE=false makes prebuilt print false.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "${root}"

repo="${DEV_PACKAGE_REPO:-ghcr.io/jonathanagustin/uds-takserver/ci-packages}"
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "dev-package: unknown machine $(uname -m)" >&2; exit 1 ;;
esac
# uds-common's create:package writes the flavored name; create:test-bundle
# copies it to the plain name before the bundle is made.
flavor="${FLAVOR:-upstream}"
file="zarf-package-takserver-${arch}-dev-${flavor}.tar.zst"

zarf() {
  uds zarf "$@"
}

# Runtime reuse inputs omit docs, tests, CI definitions, bundles, and the
# ATAK/demo/bench trees. The standalone docs site is not a package input.
# These exact spelling/license/hook configs only configure validation, not
# package contents. Keep tool pins, checkout attributes and runtime helpers.
inputs() {
  git ls-files -s -z -- . \
    ':(exclude)docs/**' ':(exclude)docs-site/**' ':(exclude)adr/**' ':(exclude)tests/**' \
    ':(exclude).github/**' ':(exclude)bundle/**' ':(exclude)atak/**' \
    ':(exclude)demo/**' ':(exclude)bench/**' ':(exclude)*.md' \
    ':(exclude)renovate.json' ':(exclude).release-please-manifest.json' \
    ':(exclude).codespellrc' ':(exclude).license_config.yaml' ':(exclude)hk.pkl' \
    ':(exclude)upstream/atak-civ' ':(exclude)takx/**' ':(exclude)upstream/takx' \
    | python3 -c '
import sys
for rec in sys.stdin.buffer.read().split(b"\0"):
    if not rec:
        continue
    meta, path = rec.split(b"\t", 1)
    mode, obj = meta.split()[:2]
    # A submodule is hashed by its pinned commit, a file by its content.
    sys.stdout.buffer.write((b"gitlink " + obj + b" " + path + b"\n") if mode == b"160000" else (b"file " + path + b"\n"))
'
}

key() {
  local sum
  sum="$(
    {
      printf 'salt=%s\n' "${KEY_SALT:-}"
      printf 'arch=%s flavor=%s\n' "${arch}" "${flavor}"
      printf 'uds=%s\n' "$(uds version 2>/dev/null || true)"
      inputs | while IFS= read -r line; do
        case "${line}" in
          gitlink\ *) echo "${line}" ;;
          'file .gitmodules')
            # TAKX is opt-in and absent from the default package. Preserve all
            # existing module metadata while ignoring only its own section.
            python3 -c '
import hashlib, pathlib, re
lines = pathlib.Path(".gitmodules").read_bytes().splitlines(keepends=True)
kept, skip = [], False
for line in lines:
    if re.match(rb"^[ \t]*\[", line):
        skip = line.rstrip(b"\r\n") == b"[submodule \"upstream/takx\"]"
    if not skip:
        kept.append(line)
print(hashlib.sha256(b"".join(kept)).hexdigest() + "  .gitmodules")
'
            ;;
          file\ *) sha256sum -- "${line#file }" ;;
          *) echo "dev-package: unexpected input line ${line}" >&2; exit 1 ;;
        esac
      done
    } | sha256sum
  )"
  echo "${arch}-${sum:0:16}"
}

ref() {
  echo "${repo}/takserver:$(key)"
}

exists() {
  zarf tools registry digest "$1" >/dev/null 2>&1
}

# True when the Package workflow run for DEV_PACKAGE_SHA has finished, so the
# tag will not appear (it failed, or this is a fork). Needs GH_TOKEN and
# GITHUB_REPOSITORY; without them, waiting falls back to the time limit.
package_run_done() {
  if [[ -z "${GH_TOKEN:-}" || -z "${GITHUB_REPOSITORY:-}" || -z "${DEV_PACKAGE_SHA:-}" ]]; then
    if [[ -z "${warned_no_api:-}" ]]; then
      echo "dev-package: GH_TOKEN, GITHUB_REPOSITORY or DEV_PACKAGE_SHA unset; waiting on the time limit only" >&2
      warned_no_api=1
    fi
    return 1
  fi
  local status
  status="$(curl -fsSL -H "Authorization: Bearer ${GH_TOKEN}" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/package.yaml/runs?head_sha=${DEV_PACKAGE_SHA}&per_page=1" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin).get("workflow_runs") or []; print(r[0]["status"] if r else "none")' 2>/dev/null)" || return 1
  if [[ "${status}" == "completed" ]]; then
    # One more look: it may have published just before finishing.
    exists "$(ref)" && return 1
    echo "dev-package: the Package run for ${DEV_PACKAGE_SHA} finished without this tag" >&2
    return 0
  fi
  return 1
}

prebuilt() {
  if [[ "${DEV_PACKAGE_REUSE:-true}" != "true" ]]; then
    echo false
    return
  fi
  local r waited=0 wait="${DEV_PACKAGE_WAIT_SECONDS:-0}"
  r="$(ref)"
  until exists "${r}"; do
    if (( waited >= wait )) || package_run_done; then
      echo "dev-package: ${r} not published; creating the package here" >&2
      echo false
      return
    fi
    sleep 15
    waited=$(( waited + 15 ))
  done
  echo "dev-package: pulling ${r} (waited ${waited}s)" >&2
  rm -f "${file}"
  if ! zarf package pull "oci://${r}" --output-directory . --no-progress >&2 || [[ ! -f "${file}" ]]; then
    echo "dev-package: pull of ${r} failed; creating the package here" >&2
    echo false
    return
  fi
  echo true
}

publish() {
  local r
  r="$(ref)"
  if exists "${r}"; then
    echo "dev-package: ${r} exists; not publishing"
    return
  fi
  [[ -f "${file}" ]] || { echo "dev-package: ${file} missing" >&2; exit 1; }
  python3 "${root}/.github/scripts/publish-dev-package.py" "${file}" "oci://${repo}" "$(key)"
  echo "dev-package: published ${r}"
}

case "${1:-}" in
  key) key ;;
  ref) ref ;;
  prebuilt) prebuilt ;;
  publish) publish ;;
  *) echo "usage: $0 key|ref|prebuilt|publish" >&2; exit 2 ;;
esac
