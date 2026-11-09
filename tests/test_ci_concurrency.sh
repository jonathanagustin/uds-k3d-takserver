#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# shellcheck disable=SC2016 # The comparisons are literal GitHub expressions.

# Superseded runs cancel only inside one workflow and one ref. Two pull
# requests do not cancel each other. A main push does not cancel a schedule,
# a manual run, a release, or Demo Video.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="${root}/.github/scripts/ci-concurrency.sh"
wf="${root}/.github/workflows"
fails=0

ok() { echo "ok: $*"; }
bad() {
  echo "not ok: $*"
  fails=$((fails + 1))
}

group() {
  "${script}" group "$@"
}

# The expression GitHub evaluates. ci-concurrency.sh implements the same rule.
gate_group='${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}-${{ (github.event_name == '"'"'schedule'"'"' || github.event_name == '"'"'workflow_dispatch'"'"') && github.run_id || '"'"'gate'"'"' }}'
gate_cancel='${{ github.event_name == '"'"'pull_request'"'"' || github.event_name == '"'"'push'"'"' }}'
full_group='${{ github.workflow }}-${{ github.job }}-${{ matrix.arch }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}-${{ (github.event_name == '"'"'schedule'"'"' || github.event_name == '"'"'workflow_dispatch'"'"') && github.run_id || '"'"'gate'"'"' }}'
full_cancel='${{ needs.changes.outputs.run == '"'"'true'"'"' && (github.event_name == '"'"'pull_request'"'"' || github.event_name == '"'"'push'"'"') }}'

pr17="$(group "Test" pull_request refs/pull/17/merge 17 100)"
pr19="$(group "Test" pull_request refs/pull/19/merge 19 101)"
push_a="$(group "Test" push refs/heads/main "" 200)"
push_b="$(group "Test" push refs/heads/main "" 201)"
pkg="$(group "Package" push refs/heads/main "" 200)"
night_a="$(group "Full Core" schedule refs/heads/main "" 300)"
night_b="$(group "Full Core" schedule refs/heads/main "" 301)"
manual="$(group "Benchmark" workflow_dispatch refs/heads/main "" 400)"
pr_cancel="$("${script}" cancel pull_request)"
push_cancel="$("${script}" cancel push)"
sched_cancel="$("${script}" cancel schedule)"
manual_cancel="$("${script}" cancel workflow_dispatch)"

eq() {
  local got="$1" want="$2" message="$3"
  if [[ "${got}" == "${want}" ]]; then
    ok "${message}"
  else
    bad "${message}: ${got}"
  fi
}
ne() {
  local got="$1" other="$2" message="$3"
  if [[ "${got}" != "${other}" ]]; then
    ok "${message}"
  else
    bad "${message}: ${got}"
  fi
}

eq "${pr17}" "Test-pull_request-17-gate" "pr 17 group"
eq "${pr19}" "Test-pull_request-19-gate" "pr 19 group"
ne "${pr17}" "${pr19}" "pull requests do not share a group"
eq "${push_a}" "Test-push-refs/heads/main-gate" "main push group"
eq "${push_a}" "${push_b}" "newer main push supersedes the older one"
ne "${push_a}" "${pr17}" "a pull request does not cancel main"
ne "${pkg}" "${push_a}" "Package does not cancel Test"
ne "${night_a}" "${night_b}" "nightly runs do not cancel each other"
ne "${night_a}" "$(group "Full Core" push refs/heads/main "" 200)" "a push does not cancel the nightly"
eq "${manual}" "Benchmark-workflow_dispatch-refs/heads/main-400" "manual run group"
if [[ "${manual_cancel}" == false && "${sched_cancel}" == false ]]; then
  ok "manual and nightly are not cancelled"
else
  bad "manual/nightly cancel flag"
fi
if [[ "${pr_cancel}" == true && "${push_cancel}" == true ]]; then
  ok "superseded PR and main pushes cancel"
else
  bad "cancel flags"
fi

require_expr() {
  local file="$1" expr="$2" label="$3" count
  count="$(grep -F -c "${expr}" "${file}" || true)"
  if [[ "${count}" == 1 ]]; then
    ok "${label}"
  else
    bad "${label} count=${count}"
  fi
}

for name in test package container cloudtak-image postgis-image atak-vm atak-e2e; do
  require_expr "${wf}/${name}.yaml" "${gate_group}" "${name} group"
  require_expr "${wf}/${name}.yaml" "${gate_cancel}" "${name} cancel"
done

bench_group='${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}-${{ (github.event_name == '"'"'schedule'"'"' || github.event_name == '"'"'workflow_dispatch'"'"' || (github.event.action == '"'"'labeled'"'"' && github.event.label.name != '"'"'benchmark'"'"')) && github.run_id || '"'"'gate'"'"' }}'
require_expr "${wf}/benchmark.yaml" "${bench_group}" "benchmark group"
require_expr "${wf}/benchmark.yaml" "${gate_cancel}" "benchmark cancel"
if grep -F -q 'cron: "41 9 * * 1"' "${wf}/benchmark.yaml"; then
  ok "benchmark schedule is weekly"
else
  bad "benchmark schedule is not weekly"
fi
if grep -F -q "github.event.label.name == 'benchmark'" "${wf}/benchmark.yaml"; then
  ok "unrelated labels do not start benchmark"
else
  bad "benchmark still starts on every labeled event"
fi

bench_validation="$(${script} benchmark-group pull_request refs/pull/17/merge 17 500 synchronize "")"
bench_label="$(${script} benchmark-group pull_request refs/pull/17/merge 17 501 labeled benchmark)"
bench_other="$(${script} benchmark-group pull_request refs/pull/17/merge 17 502 labeled full-core)"
eq "${bench_validation}" "Benchmark-pull_request-17-gate" "benchmark push stays in the validation group"
eq "${bench_label}" "${bench_validation}" "adding the benchmark label stays in the validation group"
ne "${bench_other}" "${bench_validation}" "an unrelated label does not cancel benchmark"
if [[ "$(${script} benchmark-runs pull_request synchronize "" true)" == true \
  && "$(${script} benchmark-runs pull_request labeled benchmark true)" == true \
  && "$(${script} benchmark-runs pull_request labeled full-core true)" == false \
  && "$(${script} benchmark-runs pull_request labeled benchmark false)" == false \
  && "$(${script} benchmark-runs schedule "" "" false)" == true ]]; then
  ok "benchmark matrix starts only for its own label, a push, or the schedule"
else
  bad "benchmark run predicate"
fi
if grep -F -q 'push:' "${wf}/full-core.yaml" && grep -F -q 'branches: [main]' "${wf}/full-core.yaml"; then
  ok "full-core still validates relevant main pushes"
else
  bad "full-core lost main push validation"
fi
require_expr "${wf}/codeql.yaml" '${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}' "codeql separates scheduled scans from push validation"
require_expr "${wf}/codeql.yaml" "${gate_cancel}" "codeql cancels only superseded PR and push validation"

require_expr "${wf}/full-core.yaml" "${full_group}" "full-core validate group"
require_expr "${wf}/full-core.yaml" "${full_cancel}" "full-core validate cancel"
if grep -F -q 'group: full-core-${{ github.ref }}' "${wf}/full-core.yaml"; then
  bad "full-core still queues every main run in one group"
else
  ok "full-core no longer uses one main queue"
fi

# A skipped or cancelled validation must not publish a failed aggregate.
if grep -F -q 'always() && !cancelled()' "${wf}/test.yaml"; then
  ok "verify-test does not fail a superseded run"
else
  bad "verify-test still uses if: always()"
fi
if grep -F -q "needs.validate-full-core.result != 'cancelled'" "${wf}/full-core.yaml"; then
  ok "full-core aggregate skips a cancelled validation"
else
  bad "full-core aggregate can fail when validation was cancelled"
fi

# Required checks have no path filter, so they still report on every pull request.
for name in lint codeql dependency-review commitlint; do
  if grep -E -q '^[[:space:]]+paths(-ignore)?:' "${wf}/${name}.yaml"; then
    bad "${name} has a path filter"
  else
    ok "${name} always runs"
  fi
  if grep -F -q "|| 'gate'" "${wf}/${name}.yaml"; then
    bad "${name} is in the expensive concurrency group"
  else
    ok "${name} is outside the expensive concurrency group"
  fi
done

# Release signing and the protected demo workflow are unchanged.
if grep -F -q 'group: publish-package-${{ inputs.tag || github.event.release.tag_name }}' "${wf}/release.yaml" \
  && grep -F -q 'cancel-in-progress: false' "${wf}/release.yaml" \
  && ! grep -F -q "|| 'gate'" "${wf}/release.yaml"; then
  ok "release is not cancelled"
else
  bad "release concurrency changed"
fi
if grep -F -q 'group: demo-${{ github.ref }}' "${wf}/demo.yaml" \
  && ! grep -F -q "|| 'gate'" "${wf}/demo.yaml"; then
  ok "demo concurrency is unchanged"
else
  bad "demo concurrency changed"
fi

# Reusable Docs inherits its caller's workflow name. Publication must share a
# caller-independent group while PR previews keep their ref and cancellation.
require_expr "${wf}/docs.yaml" 'group: docs-${{ github.event_name == '"'"'pull_request'"'"' && github.ref || '"'"'publish'"'"' }}' "Docs publication group is shared with reusable callers"
require_expr "${wf}/docs.yaml" 'cancel-in-progress: ${{ github.event_name == '"'"'pull_request'"'"' }}' "Docs only cancels PR previews"
require_expr "${wf}/release-please.yaml" "needs: [release-please, publish]" "Docs waits for package publication"
require_expr "${wf}/release-please.yaml" "if: needs.release-please.outputs.release-created == 'true' && needs.publish.result == 'success'" "Docs only follows a successfully published release"
require_expr "${wf}/release-please.yaml" "uses: ./.github/workflows/docs.yaml" "Release Please invokes Docs once"
require_expr "${wf}/release-please.yaml" 'release_tag: ${{ needs.release-please.outputs.tag }}' "Docs receives the published tag"
require_expr "${wf}/docs.yaml" 'git merge-base --is-ancestor "refs/tags/${RELEASE_TAG}" HEAD' "Docs verifies the released source is in main"

if ((fails > 0)); then
  echo "${fails} case(s) failed"
  exit 1
fi
