#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Look for the hosted-runner network wedge from issue #300: "ip route" blocks
# and the kernel logs hung tasks. Diagnostic only; always exits 0.
# network-stalled=true means routing timed out, so later network diagnostics
# should be skipped. A missing tool/permission is inconclusive, not a wedge.
set -u

wedged=0
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
    wedged=1
    ;;
  *) echo "Routing probe was inconclusive (exit ${route_status})." ;;
esac
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "network-stalled=${network_stalled}" >> "${GITHUB_OUTPUT}"
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hung="$(sudo -n timeout --kill-after=1s 10s dmesg -T 2>/dev/null |
  "${here}/redact-then-filter.sh" \
    --grep 'blocked for more than [0-9]+ seconds|hung_task|rtnl_lock' --tail 10 || true)"
if [[ -n "${hung}" ]]; then
  echo "Kernel hung-task lines:"
  echo "${hung}"
  wedged=1
fi

if [[ "${wedged}" -eq 1 ]]; then
  echo "::warning::This runner matches the network wedge in issue #300 (kernel=$(uname -r) ImageVersion=${ImageVersion:-unknown}). The failure may be the runner, not the product. Rerun the failed job once and add this run to https://github.com/jonathanagustin/uds-k3d-takserver/issues/300."
else
  echo "No sign of the #300 runner wedge."
fi
exit 0
