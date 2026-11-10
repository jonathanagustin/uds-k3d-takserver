#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Which changed files should start the install, upgrade, and package matrices.
# Test and Package copy the globs below into paths-ignore. tests/test_runtime_paths.sh
# fails when those lists drift, and when a runtime path is filtered out.
#
# A file that matches none of these globs is relevant. That is the safe side:
# charts, Pepr, network policies, values, bundles, tasks, image builds,
# dependency pins, and the scripts the cluster jobs run are not listed here.
# Docs, device, optional TAKX, benchmark, demo, unit tests, and metadata are.
# mise.toml is not on this list: it pins Node, k3d, Helm, the UDS CLI, and
# pnpm in the same file as the linters, so a pin-only change still starts
# Test and Package.
#
#   runtime-paths.sh globs          print the ignore globs
#   runtime-paths.sh match PATH     print "ignore" or "relevant"
#   runtime-paths.sh decide         print runtime=true|false from $CHANGED
set -euo pipefail

ignore_globs() {
  cat <<'EOF'
docs/**
adr/**
docs-site/**
assets/**
atak/**
bench/**
demo/**
upstream/atak-civ
takx/**
upstream/takx
.github/ISSUE_TEMPLATE/**
.github/pull_request_template.md
.github/test-infra/**
.github/actionlint.yaml
.github/workflows/docs.yaml
.github/workflows/lint.yaml
.github/workflows/commitlint.yaml
.github/workflows/codeql.yaml
.github/workflows/dependency-review.yaml
.github/workflows/scorecard.yaml
.github/workflows/scorecard-analysis.yaml
.github/workflows/release-please.yaml
.github/workflows/release.yaml
.github/workflows/charts.yaml
.github/scripts/publish-charts.py
.github/workflows/cosign.yaml
.github/workflows/demo.yaml
.github/workflows/benchmark.yaml
.github/workflows/full-core.yaml
.github/workflows/unit-tests.yaml
.github/workflows/mutation.yaml
.github/workflows/ui-reel.yaml
.github/workflows/atak.yaml
.github/workflows/atak-vm.yaml
.github/workflows/atak-e2e.yaml
.github/workflows/mirror-checkpoint.yaml
.github/workflows/migrate-packages.yaml
.github/scripts/migrate-ghcr.py
.github/workflows/test-aks.yaml
.github/workflows/test-eks.yaml
.github/workflows/test-rke2.yaml
.github/workflows/scan.yaml
.github/scripts/full-core-paths.sh
.github/scripts/runtime-paths.sh
.github/scripts/install-reuse-shadow.py
.github/scripts/ci-concurrency.sh
.gitignore
.gitleaks.toml
.hadolint.yaml
.yamllint
.license_config.yaml
.codespellrc
.adr-dir
LICENSE
CODEOWNERS
README.md
SECURITY.md
CONTRIBUTING.md
CHANGELOG.md
renovate.json
.release-please-manifest.json
release-please-config.json
commitlint.config.js
hk.pkl
tests/demo/**
tests/test_*
tests/playwright.demo.config.ts
pepr/capabilities/*.test.ts
pepr/mutation/**
pepr/scripts/coverage-summary.mjs
EOF
}

# GitHub path filters: * does not cross '/', ** crosses everything, and the
# pattern matches the whole path from the repository root. ? and + are not
# used. See the filter pattern cheat sheet.
glob_match() {
  local glob="$1" path="$2" re c
  re="^"
  while [[ -n "${glob}" ]]; do
    if [[ "${glob}" == '**'* ]]; then
      re+=".*"
      glob="${glob:2}"
    elif [[ "${glob}" == '*'* ]]; then
      re+="[^/]*"
      glob="${glob:1}"
    else
      c="${glob:0:1}"
      glob="${glob:1}"
      case "${c}" in
        [[:alnum:]] | '/' | '_' | '-') re+="${c}" ;;
        *) re+="\\${c}" ;;
      esac
    fi
  done
  re+="\$"
  [[ "${path}" =~ ${re} ]]
}

path_ignored() {
  local path="$1" glob
  while IFS= read -r glob; do
    [[ -z "${glob}" ]] && continue
    if glob_match "${glob}" "${path}"; then
      return 0
    fi
  done < <(ignore_globs)
  return 1
}

decide() {
  local changed="${CHANGED-}" path relevant=false
  if [[ -n "${changed}" ]]; then
    while IFS= read -r path; do
      [[ -z "${path}" ]] && continue
      if ! path_ignored "${path}"; then
        relevant=true
        break
      fi
    done <<< "${changed}"
  fi
  if [[ "${relevant}" == true ]]; then
    echo "runtime=true"
  else
    echo "runtime=false"
  fi
}

usage() {
  echo "usage: runtime-paths.sh globs|match PATH|decide" >&2
  exit 2
}

cmd="${1:-}"
case "${cmd}" in
  globs) ignore_globs ;;
  match)
    [[ -n "${2:-}" ]] || usage
    if path_ignored "$2"; then
      echo ignore
    else
      echo relevant
    fi
    ;;
  decide)
    out="${GITHUB_OUTPUT:-/dev/stdout}"
    decide >> "${out}"
    ;;
  *) usage ;;
esac
