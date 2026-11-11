#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Install, upgrade, and package run only when a changed path is relevant.
# The globs live in .github/scripts/runtime-paths.sh and are copied into
# Test and Package as paths-ignore.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="${root}/.github/scripts/runtime-paths.sh"
fails=0

ok() { echo "ok: $*"; }
bad() {
  echo "not ok: $*"
  fails=$((fails + 1))
}

match_of() {
  "${script}" match "$1"
}

check_match() {
  local path="$1" want="$2" got
  got="$(match_of "${path}")"
  if [[ "${got}" == "${want}" ]]; then
    ok "match ${path} -> ${got}"
  else
    bad "match ${path} -> ${got}, want ${want}"
  fi
}

# decide writes runtime= to $GITHUB_OUTPUT. The Unit tests job inherits that
# variable, so capturing stdout there is empty. Cover both contracts: stdout
# when it is unset, and the file when the runner set it.
check_decide() {
  local want="$1" changed="$2" got out label
  label="[${changed//$'\n'/ }]"
  got="$(env -u GITHUB_OUTPUT CHANGED="${changed}" "${script}" decide)"
  if [[ "${got}" != "runtime=${want}" ]]; then
    bad "stdout decide ${label} -> ${got}, want runtime=${want}"
    return
  fi
  out="$(mktemp)"
  got="$(GITHUB_OUTPUT="${out}" CHANGED="${changed}" "${script}" decide)"
  if [[ -n "${got}" ]]; then
    bad "runner decide ${label} also wrote stdout: ${got}"
    rm -f "${out}"
    return
  fi
  got="$(sed -n 's/^runtime=//p' "${out}")"
  rm -f "${out}"
  if [[ "${got}" != "${want}" ]]; then
    bad "runner decide ${label} -> ${got}, want ${want}"
    return
  fi
  ok "decide ${label} -> runtime=${want}"
}

# Docs, metadata, device, benchmark, demo, and unit tests do not deploy TAK.
check_match "docs/ci.md" ignore
check_match "docs/how-to/upgrade-from-0-6.md" ignore
check_match "adr/0015-full-core-is-a-scheduled-gate.md" ignore
check_match "docs-site/package.json" ignore
check_match "README.md" ignore
check_match "CHANGELOG.md" ignore
check_match "SECURITY.md" ignore
check_match "CONTRIBUTING.md" ignore
check_match "renovate.json" ignore
check_match "hk.pkl" ignore
check_match "commitlint.config.js" ignore
check_match ".github/workflows/lint.yaml" ignore
check_match ".github/workflows/codeql.yaml" ignore
check_match ".github/workflows/dependency-review.yaml" ignore
check_match ".github/workflows/unit-tests.yaml" ignore
check_match ".github/workflows/scorecard-analysis.yaml" ignore
check_match ".github/workflows/benchmark.yaml" ignore
check_match ".github/workflows/demo.yaml" ignore
check_match ".github/workflows/release.yaml" ignore
check_match ".github/workflows/mutation.yaml" ignore
check_match ".github/workflows/ui-reel.yaml" ignore
# Mutation tooling is isolated from the Pepr package used by cluster jobs.
for mutation_path in .gitignore check-report.mjs package-lock.json package.json stryker.config.mjs; do
  check_match "pepr/mutation/${mutation_path}" ignore
done
check_match "pepr/package-lock.json" relevant
check_match ".github/workflows/charts.yaml" ignore
check_match ".github/scripts/publish-charts.py" ignore
# Only this standalone read-only checker is excluded, not its producer inputs.
check_match ".github/scripts/install-reuse-shadow.py" ignore
# These exact helpers are exclusive to Docs/Demo, outside application deployment.
for optional_helper in .github/scripts/ci-apt.py .github/scripts/check-docs-browser.py .github/scripts/docs-browser-smoke.cjs .github/scripts/demo-failure-diagnostics.sh .github/scripts/select-demo-app-ref.sh; do
  check_match "${optional_helper}" ignore
  check_decide false "${optional_helper}"
  check_match "${optional_helper}.bak" relevant
  check_decide true "${optional_helper}"$'\ncharts/takserver/values.yaml'
done
# Shared diagnostics and the actual firewall remain runtime-sensitive.
for runtime_helper in .github/scripts/dump-memory.sh .github/scripts/redact-logs.py .github/scripts/node-airgap.py; do
  check_match "${runtime_helper}" relevant
done
check_match ".github/scripts/install-reuse-shadow.py.bak" relevant
check_match ".github/scripts/install-reuse-shadow-other.py" relevant
# Manual-only orchestration is distinct from shared backup/runtime helpers.
for staged_path in .github/workflows/staged-migrations.yaml .github/scripts/staged-migrations.py .github/scripts/staged-migrations.sh; do
  check_match "${staged_path}" ignore
  check_decide false "${staged_path}"
done
check_match ".github/workflows/staged-migrations.yaml.bak" relevant
check_match ".github/scripts/staged-migrations-extra.py" relevant
check_match ".github/scripts/staged-migrations.sh.bak" relevant
for shared_path in tests/backup-restore.sh tests/backup-names.sh tests/ephemeral-cluster.py tests/upgrade-agent-watch.py .github/scripts/node-agent-ready.sh tasks/test.yaml bundle/full/uds-bundle.yaml; do
  check_match "${shared_path}" relevant
  check_decide true $'.github/scripts/staged-migrations.sh\n'"${shared_path}"
done
# Deeper drivers stay sensitive; no migration directory wildcard is excluded.
for driver_path in tests/velero-ownership/drive.py tests/velero-ownership/candidate.py tests/workload-identities/drive.py tests/workload-identities/ProtocolProbe.java tests/velero-ownership/new-helper.py; do
  check_match "${driver_path}" relevant
  check_decide true $'.github/scripts/staged-migrations.py\n'"${driver_path}"
done
check_decide false $'.github/workflows/staged-migrations.yaml\n.github/scripts/staged-migrations.py\n.github/scripts/staged-migrations.sh\ndocs/ci.md\ntests/test_staged_migrations.py'
check_decide true $'.github/scripts/staged-migrations.sh\n.github/workflows/test.yaml'
check_decide true $'.github/scripts/staged-migrations.py\n.github/workflows/package.yaml'
for receipt_helper in install-receipt.py collect-install-receipt.py install-artifact-inputs.py checkpoint-identity.py; do
  check_match ".github/scripts/${receipt_helper}" relevant
  check_decide true $'.github/scripts/install-reuse-shadow.py\n'".github/scripts/${receipt_helper}"
done
check_match ".github/workflows/full-core.yaml" ignore
check_match ".github/workflows/scan.yaml" ignore
check_match ".github/test-infra/aws/eks/main.tf" ignore
check_match "atak/vm/Dockerfile" ignore
check_match "upstream/atak-civ" ignore
check_match "takx/build-commoncommo.sh" ignore
check_match "takx/patches/desktop.patch" ignore
check_match "upstream/takx" ignore
check_match "bench/run.py" ignore
check_match "demo/sync-assets.py" ignore
check_match "assets/icon.svg" ignore
check_match "tests/test_bench.py" ignore
check_match "tests/test_upgrade_baseline.py" ignore
check_match "tests/demo/tour.demo.ts" ignore
check_match "pepr/capabilities/workload.test.ts" ignore
check_match "pepr/capabilities/oidc-render.property.test.ts" ignore
check_match "pepr/scripts/coverage-summary.mjs" ignore

# Runtime, dependencies, network policy, Pepr, charts, and image builds do.
check_match "charts/takserver/templates/prereqs.yaml" relevant
check_match "charts/cloudtak/files/icon.svg" relevant
check_match "charts/takserver/templates/uds-package.yaml" relevant
check_match "pepr/capabilities/workload.ts" relevant
check_match "pepr/package-lock.json" relevant
check_match "pepr/package.json" relevant
check_match "pepr/build.sh" relevant
check_match "values/zarf-values.yaml" relevant
check_match "bundle/uds-config.yaml" relevant
check_match "bundle/full/uds-bundle.yaml" relevant
check_match "zarf.yaml" relevant
check_match "common/zarf.yaml" relevant
check_match "tasks.yaml" relevant
check_match "tasks/test.yaml" relevant
check_match "tests/upgrade.sh" relevant
check_match "tests/flows.py" relevant
check_match "tests/api-smoke.sh" relevant
check_match ".github/container-and-chart/cloudtak/Dockerfile" relevant
check_match ".github/container-and-chart/cloudtak/build.sh" relevant
check_match ".github/container-and-chart/docker/Dockerfile" relevant
check_match ".github/container-and-chart/postgis/Dockerfile" relevant
check_match ".github/workflows/test.yaml" relevant
check_match ".github/workflows/package.yaml" relevant
check_match ".github/workflows/container.yaml" relevant
check_match ".github/workflows/cloudtak-image.yaml" relevant
check_match ".github/workflows/postgis-image.yaml" relevant
check_match ".github/scripts/pin-image-tags.sh" relevant
check_match ".github/scripts/stage-sanitized-logs.sh" relevant
check_match ".github/scripts/dev-package.sh" relevant
check_match ".github/actions/attest-images/action.yaml" relevant
check_match ".gitmodules" relevant
check_match "upstream/takserver" relevant
check_match "upstream/cloudtak" relevant
check_match "mise.toml" relevant

check_decide false "docs/ci.md"
check_decide false '.github/scripts/install-reuse-shadow.py'
check_decide false $'.github/scripts/install-reuse-shadow.py\ndocs/ci-install-receipts.md\ntests/test_install_reuse_shadow.py'
check_decide true $'.github/scripts/install-reuse-shadow.py\n.github/scripts/dev-package.sh'
check_decide true $'.github/scripts/install-reuse-shadow.py\n.github/scripts/pin-image-tags.sh'
check_decide true $'.github/scripts/install-reuse-shadow.py\n.github/scripts/stage-sanitized-logs.sh'
check_decide true $'.github/scripts/install-reuse-shadow.py\n.github/workflows/test.yaml'
check_decide false $'README.md\nhk.pkl\n.github/workflows/lint.yaml'
check_decide false '.github/workflows/scorecard-analysis.yaml'
check_decide false "atak/ci/build-apk.sh"
check_decide false $'takx/build-commoncommo.sh\nupstream/takx'
check_decide true $'takx/source_inputs.py\nupstream/takserver'
check_decide true $'takx/source_inputs.py\n.gitmodules'
check_decide false "pepr/capabilities/workload.test.ts"
check_decide false $'pepr/mutation/package-lock.json\npepr/mutation/stryker.config.mjs'
check_decide true $'pepr/mutation/check-report.mjs\npepr/capabilities/workload.ts'
check_decide true $'pepr/mutation/package.json\npepr/package-lock.json'
check_decide true "charts/takserver/templates/prereqs.yaml"
check_decide true "pepr/capabilities/workload.ts"
check_decide true ".github/container-and-chart/cloudtak/Dockerfile"
check_decide true ".gitmodules"
check_decide true "mise.toml"
check_decide true $'docs/ci.md\ncharts/takserver/templates/prereqs.yaml'

# The linter pins and the install toolchain share one file. A pin-only
# change has to start Test and Package for as long as these tools are there.
mise_file="${root}/mise.toml"
for pin in 'node =' 'k3d =' 'helm =' 'pnpm =' 'aqua:defenseunicorns/uds-cli'; do
  if grep -q -F -- "${pin}" "${mise_file}"; then
    ok "mise.toml pins ${pin}"
  else
    bad "mise.toml no longer pins ${pin}"
  fi
done
check_decide true $'pepr/capabilities/workload.test.ts\npepr/capabilities/workload.ts'
check_decide false ""

# The runner's GITHUB_OUTPUT is already set when this script starts. The
# decision checks above must not read or extend that file.
inherit="$(mktemp)"
printf 'sentinel=1\n' > "${inherit}"
if GITHUB_OUTPUT="${inherit}" check_decide true "charts/takserver/templates/prereqs.yaml"; then
  if grep -q '^runtime=' "${inherit}"; then
    bad "decide appended to the inherited GITHUB_OUTPUT"
  elif [[ "$(cat "${inherit}")" == "sentinel=1" ]]; then
    ok "inherited GITHUB_OUTPUT was left alone"
  else
    bad "inherited GITHUB_OUTPUT changed: $(cat "${inherit}")"
  fi
fi
rm -f "${inherit}"

# Every tracked file under a runtime tree stays relevant. A new chart, Pepr
# source file, value, bundle, task, or image input that the globs swallow
# fails here.
must_relevant() {
  local path="$1"
  case "${path}" in
    charts/* | values/* | bundle/* | tasks/* | tasks.yaml | zarf.yaml | common/*) return 0 ;;
    .github/container-and-chart/* | .github/actions/*) return 0 ;;
    .github/workflows/test.yaml | .github/workflows/package.yaml) return 0 ;;
    .github/workflows/container.yaml | .github/workflows/cloudtak-image.yaml) return 0 ;;
    .github/workflows/postgis-image.yaml) return 0 ;;
    .gitmodules | upstream/takserver | upstream/cloudtak) return 0 ;;
    pepr/*)
      case "${path}" in
        pepr/capabilities/*.test.ts | pepr/mutation/* | pepr/scripts/coverage-summary.mjs) return 1 ;;
        *) return 0 ;;
      esac
      ;;
    tests/*)
      case "${path}" in
        tests/demo/* | tests/test_* | tests/playwright.demo.config.ts) return 1 ;;
        *) return 0 ;;
      esac
      ;;
    *) return 1 ;;
  esac
}

relevant_n=0
ignored_n=0
while IFS= read -r path; do
  got="$(match_of "${path}")"
  if [[ "${got}" == relevant ]]; then
    relevant_n=$((relevant_n + 1))
  else
    ignored_n=$((ignored_n + 1))
  fi
  if must_relevant "${path}"; then
    if [[ "${got}" != relevant ]]; then
      bad "underfiltered ${path}"
    fi
  fi
  case "${path}" in
    docs/* | adr/* | docs-site/* | atak/* | takx/* | upstream/takx | bench/* | demo/* | assets/*)
      if [[ "${got}" != ignore ]]; then
        bad "docs or device path still starts the matrix: ${path}"
      fi
      ;;
    *) ;;
  esac
done < <(git -C "${root}" ls-files)
ok "tracked files relevant=${relevant_n} ignored=${ignored_n}"

# paths-ignore in Test and Package is this glob list, twice (pull_request and push).
extract_anchor() {
  awk '
    $0 ~ /paths-ignore: &ci-ignore$/ { p = 1; next }
    p && $0 ~ /^      - "/ {
      line = $0
      sub(/^      - "/, "", line)
      sub(/"$/, "", line)
      print line
      next
    }
    p { exit }
  ' "$1"
}

for wf in test.yaml package.yaml; do
  file="${root}/.github/workflows/${wf}"
  got="$(extract_anchor "${file}")"
  want="$("${script}" globs)"
  if [[ "${got}" == "${want}" ]]; then
    ok "${wf} paths-ignore matches runtime-paths.sh"
  else
    bad "${wf} paths-ignore drifted from runtime-paths.sh"
    diff -u <(printf '%s\n' "${want}") <(printf '%s\n' "${got}") || true
  fi
  anchors="$(grep -c 'paths-ignore: &ci-ignore' "${file}")"
  aliases="$(grep -c 'paths-ignore: \*ci-ignore' "${file}")"
  if [[ "${anchors}" == 1 && "${aliases}" == 1 ]]; then
    ok "${wf} has one ignore list and one alias"
  else
    bad "${wf} anchor=${anchors} alias=${aliases}"
  fi
done

if ((fails > 0)); then
  echo "${fails} case(s) failed"
  exit 1
fi

# Exercise the actual package key without downloading or compiling packages.
python3 -B tests/test_dev_package_key.py
