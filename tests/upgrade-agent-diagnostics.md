# Agent failure evidence

`upgrade-agent-diagnostics.sh` runs only on an already failed upgrade boundary.
It retains the 30-second process-group deadline and three-second command limits.
CRI capture runs first so unavailable API calls cannot consume the entire budget.
It reads at most two k3d nodes and two agent container attempts per node, newest
first, including exited containers. Both API logs and CRI logs use source-side
80-line limits; each returned stream is sanitized before any local tail/output.
No cluster mutation, Docker inspection, environment dump or Secret read occurs.

Pod metadata includes image, explicitly configured command/args, restart count,
container IDs, termination reason, exit code and lifecycle timestamps. An
unfamiliar invocation is omitted wholesale because positional arguments can be
credentials. Empty command/args mean the image defaults apply; they do not prove
an empty process invocation. Zarf v0.88.0's published Dockerfile declares
`/zarf internal agent --log-level=debug --log-format=console --no-color`.
CRI metadata adds attempt number, state and creation timestamp when the API is
unavailable. Authentication-bearing streams, including registry auth JSON, are
omitted as a whole before other redaction and local filtering.

The fallback uses the runtime API instead of hardcoding containerd's on-disk
rotated log layout. Source contracts:

- [Zarf v0.88.0 deployment](https://github.com/zarf-dev/zarf/blob/v0.88.0/packages/zarf-agent/chart/templates/deployment.yaml): `server` container and `agent-hook` pod label.
- [Zarf v0.88.0 Dockerfile](https://github.com/zarf-dev/zarf/blob/v0.88.0/Dockerfile): image process defaults.
- [k3d default labels](https://github.com/k3d-io/k3d/blob/main/pkg/types/defaults.go): `app=k3d`; [node roles](https://github.com/k3d-io/k3d/blob/main/pkg/types/types.go): server and agent.
- [k3s multicall dispatch](https://github.com/k3s-io/k3s/blob/main/cmd/k3s/main.go): `k3s crictl` locates its configured CRI endpoint via `findCriConfig`.
- [containerd CRI container listing](https://github.com/containerd/containerd/blob/main/internal/cri/server/container_list.go): exposes CRI metadata, labels, creation time and state.
- [CRI tools logs](https://github.com/kubernetes-sigs/cri-tools/blob/master/cmd/crictl/logs.go): bounded runtime log retrieval, including terminated container IDs.

Fixtures: `python3 -m unittest discover -s tests -p test_upgrade_agent_diagnostics.py`.
These establish capture behavior and redaction; they do not reproduce the agent
crash or establish its cause. The outer deadline may truncate evidence when
multiple commands are slow. No unchanged CI retry is implied.

A manually dispatched Test workflow can select `diagnostic_case=upgrade-amd64`
(or `pg15-amd64` for the retained PostgreSQL 15 path). The selected case runs
one AMD row using the existing `TEST_RUNNER` repository variable. It skips
installs and the unselected upgrade family. This mode cannot be combined with
`trust_bundle`, is ignored for PR/push events, and reports only diagnostic
success. Default `none` preserves all ordinary matrix entries and PG15 trigger
rules. Dispatch is deliberate; no automatic retry or scheduling is added.
