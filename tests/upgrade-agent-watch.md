# Optional live agent failure evidence

Issue #400 remains unexplained. Later passing trials do not establish a fix.
The existing failure collector runs after deployment failure; this separate
watcher can preserve CPU/memory evidence closer to the first live liveness miss.
It is deliberately not enabled by default or wired into any workflow.

For an explicitly enabled, disposable k3d CI trial, start before the operation
being observed and redirect its JSON lines into the trial's diagnostic artifact:

```sh
python3 tests/upgrade-agent-watch.py --enable-ephemeral-trial --seconds 300 > agent-watch.jsonl &
watch_pid=$!
# Run the already-authorized operation and its independent acceptance gates.
# Let the finite watcher finish; its exit status is never application acceptance.
wait "$watch_pid"
```

The watcher baselines namespace event counts before its observation timestamp.
It follows the agent Service selector (at most two Pods), accepts only a current
running `server` container with a full `containerd://` ID, and triggers only on
`Unhealthy` / `Liveness probe failed:` for that Pod UID and container field path.
The event count must exceed its baseline, and its latest timestamp must follow
observation start and not precede the current container start. Readiness/startup
warnings and checkpoint event history cannot consume the capture. Event message
payloads are never emitted. The output includes numeric event/observation/capture
timestamps, current Pod UID, container ID, restart count, and node identity.

Exact container task lookup uses `k3s ctr -n k8s.io tasks list`; no CRI inspect is
read. Only a single cgroup-v2 path whose component exactly identifies that full
container ID is accepted. The five permitted files are `cpu.stat`, `cpu.max`,
`memory.current`, `memory.max`, and `memory.events`; values have strict schemas.
Task PID and cgroup identity are checked again after capture, and Kubernetes
identity is checked before and after. No paths, raw command errors, logs, process
command lines, environments, credentials, or probe URLs are output. There are no
application probes, signals, restarts, or configuration changes.

Polling sleeps at most one second; each of the three discovery calls has a
1.2-second child timeout (plus 0.1-second kill grace). Observation is limited to
1–900 seconds, including capture; output per command is capped at 1 MiB.
Docker node commands also have a one-second timeout inside the node. Missing
commands (including node `timeout`), unfamiliar schema/runtime, cgroup v1,
container exit/replacement, unavailable API, or missing metrics produce missing
or `unavailable` evidence, never a successful health assertion. The first event
can be observed only after kubelet publishes it; fast exits, API latency, event
aggregation and PID reuse races may still prevent a contemporaneous snapshot.
Only one snapshot is attempted. A deadline without a captured failure means
`unavailable-or-no-new-failure`, not a passing trial.

Local validation uses mocks only:

```sh
python3 -m unittest discover -s tests -p test_upgrade_agent_watch.py
```

These tests do not execute Docker, Kubernetes, native agent binaries, or CI jobs.
