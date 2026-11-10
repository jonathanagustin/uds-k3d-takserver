# Agent failure evidence

`upgrade-agent-diagnostics.sh` runs only after failure: upgrade boundary checks
invoke it in `tests/upgrade.sh`, Test install rows invoke it immediately
after their runner-wedge check, and Full Core invokes it immediately after its
runner-wedge check with constant phase `full-core`. The workflow callers skip
capture when a runner network stall was detected and have a two-minute step
limit around the helper's own deadline. The shared Test upgrade steps do not
invoke the install-only caller, so existing upgrade boundary capture is not
duplicated. Capturing evidence cannot turn a failed validation into success.
It retains the 30-second process-group deadline and three-second command limits.
CRI capture runs first so unavailable API calls cannot consume the entire budget.
It reads at most two k3d nodes and two agent container attempts per node, newest
first, including exited containers. Both API logs and CRI logs use source-side
80-line limits; each returned stream is sanitized before any local tail/output.
No cluster mutation, Docker inspection, environment dump or Secret read occurs.
Docker discovery, CRI listing and CRI log retrieval report their exit status.
Successful discovery with no eligible nodes, invalid CRI JSON/schema, no matching
agent attempts, and a successful empty log stream are distinct outcomes. CRI
selection reports only aggregate label-presence/match counts; it does not dump
container labels. Failed command output is sanitized as a whole before an
eight-line local tail. The final wrapper retains all individually bounded
streams, so its former 120-line tail cannot discard the first/newest CRI log.

Pod metadata includes image, explicitly configured command/args, restart count,
container IDs, termination reason, exit code and lifecycle timestamps. Live
startup/liveness/readiness timing integers and standard CPU/memory quantities
are allowlisted separately. Only the known header-free `/healthz` action on
8443 is shown; custom actions, exec commands, hosts, headers, URLs/query strings
and custom resource names are omitted. Missing timings stay missing rather
than being filled from chart defaults. An
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
failure or establish its cause. The outer deadline may truncate evidence when
multiple commands are slow. No unchanged CI retry is implied.

A manually dispatched Test workflow can select focused evidence:

| `diagnostic_case` | Selected runtime work |
| --- | --- |
| `airgap-amd64` | Existing AMD airgap install row only; receipts omitted |
| `upgrade-amd64` | Regular upgrade, AMD only |
| `pg15-amd64` | Retained PostgreSQL 15 upgrade, AMD only |
| `pg15-both` | Retained PostgreSQL 15 upgrades, AMD and ARM |

AMD uses the existing `TEST_RUNNER` repository variable; ARM uses the ordinary
native ARM runner. Upgrade selections skip installs and the unselected upgrade family.
`airgap-amd64` selects only the existing AMD airgap install row and skips both
upgrade families; its success is diagnostic-only and emits no install receipt. `pg15-both` runs the two additional main-branch PG15 paths without
repeating the three install and two regular-upgrade paths. It does not reuse
or certify any earlier result: retain the separate PR evidence for those paths.

These modes cannot be combined with `trust_bundle`, are ignored for PR/push
events, and report only diagnostic success. Default `none` preserves all ordinary
matrix entries and PG15 trigger rules. Dispatch is deliberate; no automatic
retry, scheduling or result reuse is added.

The airgap firewall uses built-in DROP for Docker embedded DNS and its terminal
deny rule, preserving the internal-network and loopback allow ordering. This
reduces dependency on an optional REJECT extension; it is not a diagnosis of
the prior hidden-stderr failure. Firewall command failures still raise and
restore node egress. Their stderr is sanitized as a whole, authentication-bearing
streams are omitted, and only a bounded single-line detail is printed. The
Docker packet fixtures assert DROP counters but remain opt-in; fixture edits
and offline rule-order tests do not establish live airgap acceptance.
