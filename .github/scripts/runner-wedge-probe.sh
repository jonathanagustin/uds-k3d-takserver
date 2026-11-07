#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Look for the hosted-runner network wedge from issue #300: "ip route" blocks
# and the kernel logs hung tasks. Diagnostic only; always exits 0.
set -u

wedged=0
if ! timeout 5 ip -4 route >/dev/null 2>&1; then
  echo "ip -4 route did not answer within 5 seconds."
  wedged=1
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hung="$(sudo timeout 10 dmesg -T 2>/dev/null |
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
