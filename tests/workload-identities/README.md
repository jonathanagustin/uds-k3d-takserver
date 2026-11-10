# Disposable workload-identity acceptance driver

`drive.py` implements a guarded shared → transition → strict → rollback → shared
trial for issue #32. It has **not run against a cluster**. Fixtures and protocol
peers validate failure handling, not real policy continuity or either architecture.
Defaults remain shared. This is not a production Helm migration command.

## Fixed scope and prerequisites

Run only from a reviewed checkout inside this repository's explicitly selected
GitHub Actions job, after the ordinary Full Core install and its initial checks.
The shared [ephemeral guard](../ephemeral-cluster.py) binds `k3d-uds` to this job,
source commit, local Unix-socket Docker daemon, actual running k3d node container,
published API port, kube-system UID and matching create-once marker. The shared pre-bootstrap operation refuses an existing/stopped cluster
or matching context before creating a trial. There is no
local/production bypass or arbitrary context/command hook. The driver also
refuses changed consumed source files.

The trial expects:

- A current shared-identity install of the same config chart and values, with
  exact Helm owners `uds-takserver-config/takserver`, `takserver/takserver` and
  `takserver-oidc/pepr-system`. The four fixed TAK Deployments and the two fixed
  module Deployment UIDs are retained. Dedicated migration RBAC must be absent
  initially; unexpected existing objects are not adopted.
- UDS Core1.16's `uds/package` and `uds/generation` policy labels, current Package
  `Ready`/`observedGeneration`, and the ambient Pod redirection annotation.
  Istio's `istio` ConfigMap in `istio-system` must use the supported root namespace
  and cluster.local trust domain. Applicable root-namespace ALLOW policies are
  examined too; unknown/broad policies stop the trial instead of being ignored.
- One Ready Ignite, PostgreSQL primary and NATS backend. Their Pod UIDs, IPs and
  ServiceAccounts must remain unchanged during the experiment. Ignite must mount
  the inspected `takserver-ignite-configmap`, have no SSL/indirect-import listener
  configuration, and contain `/opt/ignite/libs/ignite-core-2.17.0.jar`.
  A TLS or otherwise different listener needs a separate source-backed probe.
- Host `helm`, `uds`, `kubectl`, Docker, Python3.10+ with PyYAML6.0.3, and a Java
  compiler supporting `--release17`. The local k3d kubeconfig must carry inline
  client certificate/key and CA data for conditional deletion; token/exec/cloud
  authentication is refused. No client private key enters evidence or Pod probes.
- The actual application images must contain Bash, env, base64, sha256sum and a
  Java17+ runtime, with writable `/tmp`. Control Pods reuse their immutable image
  digests. Missing tools/resources are failures, never passing denials.

## What it does

The harness reads deployed config Helm values and renders the chart locally.
It changes only the real Package allow list, fixed module phase environment
fields, the four Deployment trial annotations, and explicitly named temporary
RBAC/control objects. Every API patch tests UID, resourceVersion and old value.
It never updates a Helm release, runs chart hooks, changes images, installs an
exemption or widens network policy. Helm history/values therefore remain shared
throughout this disposable test; do not use this procedure as an operator upgrade
runbook. A future supported package migration still needs its own acceptance.

For every stage it requires three stable current observations. Generated policy
selectors, complete ports and exact principals must match the requested Package
UID/rules/generation. Namespace-only/wildcard/extra principals or ports, foreign
or stale overlapping ALLOWs, terminating policies and changed NetworkPolicy
semantics stop progress. Duplicate identical NetworkPolicies during the dual
phase do not count as wider access.

Before admission changes, transition or rollback policies must already converge.
The two actual Pepr Deployments roll to the requested phase with no old/terminating
phase Pods. A real update of each existing TAK Deployment exercises the installed
adapter. Every controlled ReplicaSet/Pod is checked, including old owners and
terminating replicas. No standalone, mislabeled, mixed-account or stale-generation
Pod can be omitted to make rollout pass.

Fresh **application-data reachability** checks cover every live migrated Pod:

- All four workloads read Ignite2.17's18-byte NodeId greeting: little-endian
  message type -1 plus a nonzero UUID. They do not join the cluster or touch cache
  data. This is protocol reachability, not a successful Ignite application RPC.
- API, messaging and plugins also receive a PostgreSQL SSLRequest response and
  NATS INFO greeting. No database authentication/write or NATS publication occurs.
- For each source, paired unready, Job-controlled probe Pods use the same actual image and
  identical app labels, but one uses the permitted account and the other an
  unrelated account. They are created with a neutral label, then relabeled using
  guarded Pod metadata updates: the existing CREATE-only app injector would
  otherwise start the real application initialization, which is not this probe.
  No webhook or policy is disabled. Both control network/DNS paths are checked.
  A real controlling Job prevents adoption by a Deployment ReplicaSet; its
  selector labels and controller UID are preserved and checked after relabeling.
  The permitted control and real application must receive data before and after
  the denied control receives none. In strict mode, a legacy-account control is
  additionally denied on PostgreSQL. Ignite legitimately retains its legacy
  identity, so the driver does not pretend every legacy flow can be denied.

The helper strips Java option environment variables only for its own tiny JVM,
with bounded heap/metaspace; it does not change the application's environment.
TCP connect alone, kubectl errors, malformed/partial protocol frames and an
unready positive backend cannot pass. Protocol source references are in
[protocol-contract.json](protocol-contract.json). These are representative live
paths for each changed identity, not a claim to exercise every allowed port or
all TAK features.

Reverse stages dual policies first, restores all workload identities, verifies
traffic, removes transitional rules, verifies shared traffic and conditionally
removes only trial-created objects. Job deletion uses Foreground propagation,
and recorded child Pod UIDs must disappear before the controls are marked gone. DELETE requests carry actual API UID and
resourceVersion preconditions; already-absent recorded objects are idempotent,
and a replacement UID is refused. Private atomic journals retain every completed
stage, resource identity, protocol result and failure. Failed stages do not trigger
blind cleanup or automatic rollback. Explicit recovery is never marked accepted and recompiles the fixed helper
source rather than trusting executable bytes from the saved journal.

## Concrete manual-only trial plan (pending review)

Do not dispatch until the driver and workflow wiring are reviewed. Add an explicit
manual scenario to the existing native Full Core jobs; ordinary PR/push/scheduled
runs must keep their current shared path and never call this driver. Reuse warm
published images; do not add image builds, a cold matrix or a larger runner.

1. Check the local Docker endpoint before bootstrap with
   `python3 tests/ephemeral-cluster.py bootstrap --context k3d-uds`. Install the
   ordinary Full Core/shared package and pass its initial application checks.
2. Explicitly mark the verified disposable cluster:
   `python3 tests/ephemeral-cluster.py mark --context k3d-uds`. If the job needs a
   kubectl wrapper, use the already installed `uds zarf tools kubectl`, not a
   different context or remote Docker daemon.
3. Run from the checkout, with a new private output directory:

   ```bash
   uv run --no-project --with pyyaml==6.0.3 python3 \
     tests/workload-identities/drive.py round-trip \
     --evidence "$RUNNER_TEMP/identity-trial/journal.json"
   ```

   The driver stops at40minutes, each observation wait is at most5minutes, each
   exec20seconds, and each socket operation3seconds. Give the hosted step an
   independent45minute ceiling. These are hard ceilings, not measured runtimes.
4. Re-run the existing Full Core API/flow acceptance on the restored shared
   installation. Retain architecture, source/run/attempt, sanitized driver
   journal privately and the existing bounded test summaries. Publish only the
   common verifier’s allowlisted stage/receipt/hash fields, not the raw recovery
   journal. Never recursively upload the private directory: kubeconfigs, raw Helm values/manifests, credentials or keys
   do not belong in public artifacts.
5. If interrupted, inspect the exact stopped stage. A reviewed recovery step may
   explicitly run `reverse --evidence ...` in the **same** job/cluster/source.
   Unknown ownership, changed chart/mesh/values, replacement UIDs, unrecorded
   resources or unsafe partial creation require manual review; the driver does
   not infer a successful migration from recovery. Preserve evidence, not an
   unconditional namespace/resource cleanup handler.
6. Pilot one native architecture first, then the other after reviewing the
   actual result. Both must pass forward/strict/reverse and the ordinary
   application checks before changing issue #32's live acceptance status.

A normal green Full Core run does not execute this experiment. No hosted selector,
cluster mutation, dispatch or real acceptance result is supplied by these files.

Offline tests:

```bash
uv run --no-project --with pyyaml==6.0.3 python3 -B -m unittest \
  tests.test_identity_rollout_driver tests.test_ephemeral_cluster -v
```
