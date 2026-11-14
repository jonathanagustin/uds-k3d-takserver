# Disposable workload-identity acceptance driver

`drive.py` implements a guarded shared → transition → strict → rollback → shared
trial for issue #32. Live acceptance is still required on both architectures. Fixtures and protocol
peers validate failure handling, not real policy continuity.
Defaults remain shared. This is not a production Helm migration command.

## Fixed scope and prerequisites

Run only from a reviewed checkout inside this repository's explicitly selected
GitHub Actions job, after its Unified Defense Stack (UDS) Core install and shared-baseline checks.
The shared [ephemeral guard](../ephemeral-cluster.py) binds `k3d-uds` to this job,
source commit, local Unix-socket Docker daemon, actual running k3d node container,
published application programming interface (API) port, the kube-system unique identifier (UID) and matching create-once marker. The shared pre-bootstrap operation refuses an existing/stopped cluster
or matching context before creating a trial. There is no
local/production bypass or arbitrary context/command hook. The driver also
refuses changed consumed source files.

The trial expects:

- A current shared-identity install of the same config chart and values, with
  exact Helm owners `uds-takserver-config/takserver`, `takserver/takserver` and
  `takserver-oidc/pepr-system`. The four fixed Team Awareness Kit (TAK) Deployments and the two fixed
  module Deployment UIDs are retained. Dedicated migration role-based access control (RBAC) must be absent
  initially; unexpected existing objects are not adopted.
- UDS Core 1.16's `uds/package` and `uds/generation` policy labels, current Package
  `Ready`/`observedGeneration`, and the ambient Pod redirection annotation.
  Istio's `istio` ConfigMap in `istio-system` must use the supported root namespace
  and cluster.local trust domain. Applicable root-namespace ALLOW policies are
  examined too; unknown/broad policies stop the trial instead of being ignored.
- One Ready Ignite, PostgreSQL primary and NATS backend. Their Pod UIDs, Internet Protocol (IP) addresses and
  ServiceAccounts must remain unchanged during the experiment. Ignite must mount
  the inspected `takserver-ignite-configmap`, have no Secure Sockets Layer (SSL) or indirect-import listener
  configuration, and contain `/opt/ignite/libs/ignite-core-2.17.0.jar`.
  A Transport Layer Security (TLS) or otherwise different listener needs a separate source-backed probe.
- Host `helm`, `uds`, `kubectl`, Docker, Python3.10+ with PyYAML6.0.3, and a Java
  compiler supporting `--release17`. The local k3d kubeconfig must carry inline
  client certificate/key and certificate authority (CA) data for conditional deletion; token/exec/cloud
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
  message type -1 plus a nonzero universally unique identifier (UUID). They do not join the cluster or touch cache
  data. This is protocol reachability, not a successful Ignite application remote procedure call (RPC).
- API, messaging and plugins also receive a PostgreSQL SSLRequest response and
  NATS INFO greeting. No database authentication/write or NATS publication occurs.
- For each source, paired unready, Job-controlled probe Pods use the same actual image and
  identical app labels, but one uses the permitted account and the other an
  unrelated account. They are created with a neutral label, then relabeled using
  guarded Pod metadata updates: the existing CREATE-only app injector would
  otherwise start the real application initialization, which is not this probe.
  No webhook or policy is disabled. Both control network paths and Domain Name System (DNS) resolution are checked.
  A real controlling Job prevents adoption by a Deployment ReplicaSet; its
  selector labels and controller UID are preserved and checked after relabeling.
  The permitted control and real application must receive data before and after
  the denied control receives none. In strict mode, a legacy-account control is
  additionally denied on PostgreSQL. Ignite legitimately retains its legacy
  identity, so the driver does not pretend every legacy flow can be denied.

The helper strips Java option environment variables only for its own small Java virtual machine (JVM),
with bounded heap/metaspace; it does not change the application's environment.
Transmission Control Protocol (TCP) connect alone, kubectl errors, malformed/partial protocol frames and an
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
     --candidate-plan "$RUNNER_TEMP/staged-migrations/candidate/plan.json" \
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

## Supported package phase acceptance (explicit opt-in)

The manual workflow additionally offers `identity_method=package` or `combined`
with `scenario=identities`. The default remains the existing manual trial;
ordinary workflows never activate this experiment. `combined` runs the existing
manual round trip first, then the package path on its restored shared baseline.

The package path reuses one downloaded application archive, verified by its
recorded hash, and the bound staged configuration. It deploys actual Zarf package values through
`shared -> transition -> strict -> rollback -> shared`. `rollback` is the reverse
transition: both principal sets remain allowed while admission restores legacy
accounts. Selecting `transition` again would continue forcing dedicated accounts.
No phase is implemented by patching the Package, Deployments or Pepr environment.
Only the existing UID-bound disposable probe Job/Pod controls are created/labeled.

Pinned command-line interface (CLI) capability checks run before cluster creation. Each deployment rechecks
archive/config hashes, the job-local cluster guard and default context. Read-only
policy, workload and Pepr validators require convergence; the same protocol
positive/negative controls run with unchanged credentials and protocol paths.
Each phase also runs existing web TLS, Marti API and flow checks. Complete bounded
phase snapshots are projected into private immutable files and replayed by the
same pure validators before fixed public verdicts are emitted. A boolean alone
cannot establish acceptance; unsupported/missing observations fail closed.

`fresh_strict=true` additionally authorizes removal of only the bound `takserver`
application package after a successful reversal. Core namespace/controller/Package
UIDs must remain unchanged, except for the exact source-owned shared ambient
egress Deployment described below. The source-owned local backup node-agent is part of
this application package; it is distinguished from the retained Core Velero server.
Before removal, cleanup binds exact application persistent volume claim (PVC) UIDs and persistent volume (PV) claim references and
StatefulSet/chart ownership, stored Helm hooks, and the known certificate generator.
After all consumers are gone, only these exact retained objects may be deleted,
using API UID/resourceVersion preconditions. Unknown or foreign leftovers refuse
fresh acceptance; no namespace deletion or broad PVC/Secret cleanup is used.
The same archive then installs strict with new application UID baselines and the
original Core guard. This is separate from migration/rollback acceptance.

Core 1.16.0 intentionally removes `istio-egress-ambient/egress-waypoint` when
its last ambient `remoteHost` consumer leaves ([pinned controller source](https://github.com/defenseunicorns/uds-core/blob/fd9769cd9e791d9b6ad86251af0f4899992a9ae5/src/pepr/operator/controllers/istio/egress-ambient.ts)).
The trial binds the exact Gateway spec, source labels and consumer annotations,
Gateway/derived Deployment UIDs, Core namespace UID, and the Helm-owned
application Package UIDs before removal. The Deployment must carry the exact
four-field Gateway owner reference and mesh-controller/class labels from
[pinned Istio 1.31.2](https://github.com/istio/istio/blob/e2f3a7949a358af7dd901a6f9ccd6ecdd7270271/manifests/charts/istio-control/istio-discovery/files/waypoint.yaml);
its source template omits `controller` and `blockOwnerDeletion`. Only this derived Deployment has a separate
lifecycle; every other Core workload and the mesh hash retain their original guard.
A foreign consumer preserves the original exact Core snapshot instead. Cleanup
requires three consecutive absent observations within 60 seconds, never deletes
Core resources, and rejects changed ownership, replacement UIDs or new consumers.
Fresh installation can rebind only an originally bound, verified-removed singleton
with the same consumer identities and retained Core namespace. Unsupported Core
versions refuse this exception. These guards are source-tested; another native
package pilot must validate the live ownership/defaulted-spec contract before acceptance.

Across the five phase deployments, private credential-data hashes must remain
unchanged. The known `before-hook-creation` keystore Secret may legitimately get a
new UID while retaining identical data and hook ownership. PVC/PV identities remain
stable, and an exact generated test-only file on each application data volume must
retain its hash. Only that owned file is removed; no database file is overwritten.
Hashes and retained-object metadata stay private and are not public artifact fields.

The package trial has its own 120-minute wall budget and 125-minute outer timeout;
individual deployments are capped at25minutes and explicit package removal at15.
No live execution or architecture acceptance is implied by these source fixtures.
Both native architectures still require actual supported-package and clean strict
results before the issue's remaining acceptance can be claimed.

Typed phase evidence is bounded to256KiB per phase and16 private0600 files in a
0700 directory. It records complete root/local policy list resource versions and
counts, safe workload identities and hashes of complete original templates/specs.
Pod environment, commands and full annotations are excluded. Each snapshot is
replayed through the same policy, workload and Pepr guards; missing old facts or
unsupported credential-capable conditions produce insufficient evidence rather
than being silently dropped. Bound API versions and Package custom resource definition (CRD) schema identity
also accompany rendering, so API capability/default changes cannot be waived.
Public output contains fixed verdicts and reviewed input/guard/capture hashes,
not private manifests. Existing f3c09ad1 runs do not establish this new schema's
acceptance merely because their booleans or phase names look similar.

Known API-generated retained state is source-bound rather than broadly ignored:
`takserver-startup` must have the literal completed startup annotation and ready
value. The CloudTAK admin copy must have its source label and exactly match the
current certificate/keystore parents. The optional watcher enrollment cache is
recognized only by its source label; active TakClient resources prevent retirement.
UID/resourceVersion checks still apply to every exact deletion.

Known infrastructure trust maps are never deleted by this cleanup. Before removal,
their exact UID, public certificate data and source metadata are bound to the
retained Kubernetes/Istio/Core authority map UID/data. The UDS bundle additionally
requires the exact Package owner reference and controller labels from Core1.16.
Only these bound observations may remain during clean-state checks; a reserved
name alone, an extra payload, or changed UID/data/source still refuses acceptance.

CloudTAK is required, not an optional skip, for this issue's package acceptance.
The existing `test:cloudtak` task runs at baseline, strict and fresh strict, including
its actual basemap positive/negative checks. Component identities are checked on
both sides and explicit passed stages are required by the publisher. Other phases
retain TLS/API/flow checks without repeatedly invoking mutation-heavy `test:all`.

### Failed package trial diagnostics

The package wrapper retains the first failure even when initialization stops
before a trial ID or normal journal exists. Its private
`PRIVATE-failure-callsite.json` contains only the source/run identity, a fixed
exception type, and reviewed relative source filenames, line numbers and source
hashes. It records no exception message, local variables, command arguments,
command output or Kubernetes objects. Capture and publication both check the
allowlisted files against the exact reviewed checkout; missing, changed or
oversized evidence stays unavailable.

Failure publication reads the selected manual and package journal paths
independently. It publishes allowlisted stage names and phase aliases, plus
validated callsites and fixed failure categories when available. These are
partial progress diagnostics, never an acceptance result. A genuine Package
preflight mismatch also prints only its existing safe field paths and whole-spec
hashes after its exclusive private write succeeds; unknown map keys remain
opaque hashes and no spec values or rendering inputs are printed.

Reviewed web TLS, API smoke, flow and CloudTAK checks use the same bounded
subprocess runner as package commands. On failure, their first private stream
snapshot is available to the opt-in encrypted diagnostic, bound to the exact
source, run, attempt, check and phase. Each stream is bounded and the full
snapshot is at most 64 KiB, written exclusively with mode 0600. Public progress
contains only the fixed check/phase, status and stream-presence flags. The first
private failure remains selected across package, retained-state and application
checks; a successful check or diagnostic capture never changes acceptance.

Both manual and package trials bind the reviewed candidate plan and its config
hash before rendering. Zarf replaces `###ZARF_VAR_DOMAIN###` after Helm rendering;
the shared expected-render path now emulates only that known token using the
bound config's DOMAIN. It does not infer a domain from a live URL or omit SSO
fields. All other Helm data, discovery/schema checks and exact specification
comparison remain unchanged. Plan/config drift or an unbound token fails closed.

The Pepr chart finalizer (`pepr/scripts/finalize-chart.mjs`) includes the
`takclients` Namespace in the application's `takserver-oidc` release, installed
in `pepr-system` by `common/zarf.yaml`. Its namespace identity is therefore bound
separately from Core only when the baseline has that exact Helm owner and managed
label. The binding freezes the original UID (unique identifier); ownership changes,
replacement during the round trip, and unexpected disappearance still fail.
Only successful application removal permits absence. A new namespace binding is
allowed only after the supported fresh installation and exact owner checks.
Pre-existing foreign namespaces stay in the Core inventory. Every observed
Deployment, StatefulSet, DaemonSet and Package in `takclients` remains guarded, so
namespace ownership never permits unrelated workloads to disappear.

Core UID or mesh-hash drift also emits a fixed public category and change type.
The optional encrypted diagnostic retains the first bounded before/after UID and
hash maps, with the same source/run/attempt binding as retained-hook diagnostics.
It contains no Kubernetes resource bodies or mesh configuration values. Invalid
maps, private-file changes, unsupported kinds or diagnostic I/O errors cannot
turn the original Core guard failure into acceptance. Source fixtures establish
this classification defect; they do not prove the exact changed inventory key in
run43499139100, which did not retain that snapshot. A new live pilot is required.
The typed maps cover completed inventory comparisons. A missing required Core
namespace or a changed bound application owner fails before a complete snapshot
exists; those failures retain the reviewed callsite rather than partial maps.

If retained-state diagnostic capture itself fails, a separate first-failure
callsite records only its reviewed file/line hashes and fixed exception type.
The publisher revalidates it under `identityDiagnosticFailures`; the primary
invariant's callsite remains under `identityFailures`. Neither channel includes
exception text, inventory keys or private payloads. Failure of either optional
capture still leaves the original Core or retained-data guard failed.


The optional encrypted channel reports only source-owned rejection codes after
`private-input:` when input eligibility fails. These distinguish missing private
references, journal/progress reads or bindings, retained files, reviewed source,
and retained schemas. They contain no exception messages, resource names, values,
or paths. A rejected channel never authorizes private bytes; exactly one eligible
channel is still required. These codes diagnose evidence delivery and do not
explain or relax the retained-Core assertion.
