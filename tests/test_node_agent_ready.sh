#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The same function backup-restore.sh uses. Fixtures are the node-agent
# lines from Full Core run 42366545433, plus lines that must not match.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=.github/scripts/node-agent-ready.sh
source "${root}/.github/scripts/node-agent-ready.sh"

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

expect_yes() {
  if printf '%s\n' "$2" | node_agent_controllers_started; then
    ok "$1"
  else
    bad "$1 was rejected"
  fi
}

expect_no() {
  if printf '%s\n' "$2" | node_agent_controllers_started; then
    bad "$1 was accepted"
  else
    ok "$1"
  fi
}

# Velero 1.18 controller-runtime, from the node-agent log at 11:20:10Z.
expect_yes "actual Starting Controller line" \
  'time="2026-11-07T11:20:10Z" level=info msg="Starting Controller" controller=podvolumebackup controllerGroup=velero.io controllerKind=PodVolumeBackup'

expect_yes "older Starting controllers line" \
  'time="2020-01-01T00:00:00Z" level=info msg="Starting controllers" controller=podvolumebackup'

expect_no "Starting workers" \
  'time="2026-11-07T11:20:10Z" level=info msg="Starting workers" controller=podvolumebackup worker count=1'

expect_no "Starting EventSource" \
  'time="2026-11-07T11:20:10Z" level=info msg="Starting EventSource" controller=datadownload source="kind source: *v1.Pod"'

expect_no "a sentence that only mentions a controller" \
  'the node-agent controller is starting'

expect_no "empty log" ""

# More than a pipe buffer after the early match must not SIGPIPE the log
# producer. The real caller runs this pipeline with pipefail enabled.
if python3 - <<'PY' | node_agent_controllers_started
import signal
import sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
sys.stdout.write("Starting Controller\n")
sys.stdout.flush()
for _ in range(2000):
    sys.stdout.write("ordinary log line " * 100 + "\n")
PY
then
  ok "early match drains a large log stream"
else
  bad "early match interrupted the log producer"
fi

# A matching line must not hide a real failure from kubectl.
if bash -c 'printf "Starting Controller\n"; exit 42' | node_agent_controllers_started; then
  bad "matching line masked the producer failure"
else
  ok "producer failure still fails the readiness pipeline"
fi

if ! grep -q 'node_agent_controllers_started' "${root}/tests/backup-restore.sh"; then
  bad "backup-restore.sh does not use node_agent_controllers_started"
else
  ok "backup-restore.sh uses the tested function"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
