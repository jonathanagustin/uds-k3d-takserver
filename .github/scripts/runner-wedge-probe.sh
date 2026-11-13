#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Look for the hosted-runner network wedge from issue #300: "ip route" blocks
# and the kernel logs hung tasks. Diagnostic only; always exits 0.
# network-stalled=true means routing timed out, so later network diagnostics
# should be skipped. A missing tool/permission is inconclusive, not a wedge.
#
# A task in uninterruptible sleep ignores KILL, and waiting for it would hold
# the Actions step until timeout-minutes fails the step. The outer deadline
# does not wait for that child. It still exits 0 and records a stall when the
# probe wrote nothing.
set -u

if [[ "${WEDGE_PROBE_INNER:-}" != 1 ]]; then
  deadline="${WEDGE_PROBE_DEADLINE:-20}"
  if [[ ! "${deadline}" =~ ^[1-9][0-9]*$ ]]; then
    echo "runner-wedge: deadline must be a positive integer" >&2
    exit 2
  fi
  # Descendants must not retain the Actions stdout/stderr pipes after the
  # wrapper exits. Spool diagnostic output, already redacted by the inner probe.
  probe_log="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/runner-wedge.XXXXXX")" || exit 0
  setsid env WEDGE_PROBE_INNER=1 bash "$0" > "${probe_log}" 2>&1 &
  probe_pid=$!
  elapsed=0
  while kill -0 "${probe_pid}" 2>/dev/null; do
    if [[ "${elapsed}" -ge "${deadline}" ]]; then
      kill -TERM -- "-${probe_pid}" 2>/dev/null || true
      sleep 1
      kill -KILL -- "-${probe_pid}" 2>/dev/null || true
      cat "${probe_log}"
      rm -f "${probe_log}"
      echo "runner-wedge probe did not finish within ${deadline}s."
      if [[ -n "${GITHUB_OUTPUT:-}" ]] && ! grep -q '^network-stalled=' "${GITHUB_OUTPUT}" 2>/dev/null; then
        echo "network-stalled=true" >> "${GITHUB_OUTPUT}"
      fi
      exit 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  wait "${probe_pid}" 2>/dev/null || true
  cat "${probe_log}"
  rm -f "${probe_log}"
  exit 0
fi

network_stalled=false
# A TERM-only timeout can itself wait forever for a blocked child. Escalate
# to KILL after one second. This bounds the probe process; it cannot recover
# a task in uninterruptible kernel sleep or repair the runner kernel.
timeout --kill-after=1s 5s ip -4 route >/dev/null 2>&1
route_status=$?
case "${route_status}" in
  0) ;;
  124|137)
    echo "ip -4 route did not answer within 5 seconds."
    network_stalled=true
    ;;
  *) echo "Routing probe was inconclusive (exit ${route_status})." ;;
esac
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "network-stalled=${network_stalled}" >> "${GITHUB_OUTPUT}"
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Kernel collection has its own finite command/output bounds. It captures full
# traces, redacts complete streams, and claims SysRq-w once only when routing
# actually timed out. The outer process-group deadline remains the final bound.
python3 -B "${here}/runner-wedge-kernel.py" --network-stalled "${network_stalled}" || true
exit 0
