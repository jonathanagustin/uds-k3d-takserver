# Opt-in Velero ownership experiment

This is an experimental preparation, observer and guarded disposable-cluster
acceptance harness for [issue 258](https://github.com/jonathanagustin/uds-takserver/issues/258),
not a production migration command. The observer is read-only; the separately
invoked staged driver deliberately mutates only its verified ephemeral cluster.
FILESYSTEM_BACKUP remains false by default and FILESYSTEM_BACKUP_OWNER remains
local. A direct switch on an existing installation can delete its current agent
and configuration. Live acceptance is still pending.

## Reviewed inputs

Core 1.16.0 includes the uds-exemptions chart in core-base; its custom exemptions
are installed before core-backup-restore. Core pins Velero chart 12.2.1, whose
node-agent selector matches the local immutable `name: node-agent` selector.
It supports nodeAgent.annotations, contexts, resources and args, and prefixes
its configMaps with the release name. See the exact source links in
[ADR 0021](../../adr/0021-velero-node-agent.md).

Helm 4.3.0 defaults to server-side apply. The candidate keeps
`helm.sh/resource-policy: keep` in the Core **desired** agent annotation, as
well as requiring protection of the live old agent during a handoff. A one-time
live annotation patch is not evidence that a later desired manifest preserves
it. Field-manager conflicts must be observed, not bypassed using blind force.
The unmodified standard bundle continues to use the local owner.

## Prepare a separate candidate

With trusted pinned Helm and Python/PyYAML, render only the local exemption:

```bash
helm template takserver charts/takserver --namespace takserver \
  --set-string backup.filesystem.enabled=true \
  --show-only templates/filesystem-backup.yaml > /tmp/agent-resources.yaml
# Extract the single Exemption YAML document, preserving its spec exactly.
# Use a reviewed YAML tool or Python/PyYAML, not textual regex extraction.
python3 tests/velero-ownership/prepare.py \
  --bundle bundle/full/uds-bundle.yaml \
  --exemption /tmp/agent-exemption.yaml \
  --output /tmp/ownership-experiment-bundle.yaml
```

The generator copies its inputs, verifies the reviewed package versions and
policy/matcher sets, preserves existing custom exemptions and HOME override,
adds a separately named equivalent bootstrap exemption and the reviewed upstream
agent/config values, and refuses an existing bootstrap or overlapping agent
setting. It refuses to overwrite any output. It neither deploys the result nor
changes the full-bundle config. Independently prepare a separate uds-config
copy with `variables.takserver.FILESYSTEM_BACKUP_OWNER: core` for the Core-owner
stages; retain FILESYSTEM_BACKUP=true and the full bundle's storage classes.
The package passes this owner via its existing pre-render valuesFiles path.

## Bounded observer stages

Always use an explicit ephemeral cluster context and a new evidence directory:

```bash
python3 tests/velero-ownership/observe.py --context EPHEMERAL_CONTEXT \
  --directory out/ownership-proof --stage local-before
```

The observer limits every read command to 45 seconds and does not poll. Missing
resources, unknown owners, another cluster, a changed DaemonSet UID/selector,
incomplete rollout, wrong pod config, mismatched bootstrap, stale release
manifests or changed proof-tool bytes fail. Each accepted stage file is created
exclusively, never overwritten. Helm manifests can contain credentials: the
observer keeps those in memory, filters to the known agent/config resources,
and saves only sanitized identity/status summaries, hashes and volume-copy
identities. Do not upload raw `helm get manifest` output.
Terminating agent DaemonSets, Pods and configuration are rejected even when
their last reported readiness or ownership still matches the expected stage.

After a separately reviewed real migration, record `core-ready`. This checks
that Core's stored manifest owns the actual agent/config, TAK's manifest no
longer includes them, the original DS UID survives, and all agents are Ready
with the new config. Run the existing destructive full-core backup/restore
acceptance on the disposable cluster, then record:

```bash
python3 tests/velero-ownership/observe.py --context EPHEMERAL_CONTEXT \
  --directory out/ownership-proof --stage core-after \
  --backup ACTUAL_BACKUP_NAME --restore ACTUAL_RESTORE_NAME
```

The backup must have been created after core-ready was observed. Backup and
Restore must be cleanly Completed, refer to each other, and have Completed data
PodVolumeBackup/PodVolumeRestore objects for both takserver and cloudtak. The
existing `tests/backup-restore.sh` and post-restore API smoke must also succeed;
the observer does not infer application health from Velero status.

Reverse migration uses `local-ready` then a **new** backup/restore and
`local-after`, retaining the original local-before UID and requiring prior
core-after evidence. A fresh Core-owned installation uses a separate evidence
directory and `fresh-ready` then `fresh-core`; it is not handoff/reversal proof.
A readiness observation is a bounded sample, not an atomic transaction or a
claim that no subsequent cluster change occurred.

Offline checks (no cluster, downloads or ownership writes):

```bash
uv run --no-project --with pyyaml==6.0.3 python -B -m unittest \
  tests.test_filesystem_backup_owner tests.test_velero_handoff \
  tests.test_ephemeral_cluster tests.test_velero_transfer tests.test_velero_trial -v
```

## Guarded staged driver (not yet accepted live)

`candidate.py`, `transfer.py`, and `drive.py` implement an opt-in disposable
acceptance harness. They do not change production defaults. The commands are
not a supported production migration procedure and must not be used on a
persistent cluster.

The shared `tests/ephemeral-cluster.py` guard binds every outer mutation to
this repository's exact GitHub Actions run, attempt, source SHA, local Docker
Unix socket, fixed `k3d-uds` context, API port, server container ID, cluster UID
and nonterminating run marker. Run its `docker` operation **before bootstrap**,
then `mark` only after creating that run's disposable cluster. Docker environment
and non-default contexts are refused, including remote endpoints. There is no
local/production override. The marker is never overwritten.

Prepare in a fresh private runner directory after pinning the existing image
keys and acquiring the exact dev package. Core packages retain their keyless checks; the local
experimental bundle/dev package is not claimed to be a signed release. Extract the actual single local
Exemption from a Helm render as above, then:

```bash
python3 tests/velero-ownership/candidate.py prepare \
  --exemption "$RUNNER_TEMP/agent-exemption.yaml" \
  --directory "$RUNNER_TEMP/owner-candidate"
# The usual bundle helper copies the flavored dev package to its unflavored
# name. Do the same reviewed copy before create, without compiling new images.
for variant in core detach clean; do
  uds create "$RUNNER_TEMP/owner-candidate/$variant" --confirm \
    --output "$RUNNER_TEMP/owner-candidate/$variant"
done
python3 tests/velero-ownership/candidate.py bind \
  --directory "$RUNNER_TEMP/owner-candidate"
python3 tests/velero-ownership/drive.py round-trip \
  --plan "$RUNNER_TEMP/owner-candidate/plan.json" \
  --evidence "$RUNNER_TEMP/owner-trial"
```

The prepared core variant contains only Core base, backup/restore and TAK with
CloudTAK. The detach variant omits Core's agent but retains its config; clean
omits that config too. Both retain the remaining reviewed Velero overrides.
Relative package/values-file paths are relocated rather than silently changed.
Binding checks prepared bytes and records actual archive hashes against the
workflow SHA. The driver rechecks bytes before deploy, uses UDS 0.41 package
selection and `UDS_CONFIG`, and permits one deployment attempt (`--retries 1`).
Zarf treats zero retries as its default; zero would not disable retries.

Only the initial `core` archive's `core-base` bootstrap, with no owner override,
uses `--force-conflicts` to establish the same Core compatibility baseline as
the ordinary full-core test. The first named bootstrap stage must be running;
recovery and later phases cannot use this exception. Immediately before
dispatch, the driver requires successful reads proving both the Velero server
and node-agent DaemonSet absent, rehashes the bound archive/config and verifies
the disposable cluster again. Existing or terminating objects and read errors
refuse this path. The four-input plan, Core package signatures and optional
passthrough gateway selection remain intact.

This permits real SSA field-manager migration across the selected Core-base
charts and their rollback, including the checkpoint's Gateway API transition.
It is a guarded baseline operation on this fresh disposable cluster; it is not
a general production migration instruction. Every backup/restore, TAK,
handoff, transfer and reversal deployment remains flag-free. Separate
take-ownership/adopt flags, insecure options and signature bypass stay disabled.

The fixed sequence is fresh Core-agent-first installation and real
backup/restore/API acceptance; conversion to a known local baseline; then
local-to-Core and Core-to-local, each with new acceptance. It keeps the same
DaemonSet UID throughout and records separate fresh/handoff proofs. Three
backup names use the explicit fresh/core/local suffix without changing the
GitHub run identity. The backup helper's trial mode fixes its context and
rechecks the shared guard before its mutating kubectl calls. Initial Core
bootstrap requires no existing Velero server or agent; later phases refuse
active, unknown or terminating Velero work, unpaused schedules and live data
movers. Metadata writes use API JSON Patch tests for the exact UID,
resourceVersion, old Helm owner and managed-by label. A concurrent update
fails instead of being retried or forced. These are bounded observations, not
an atomic lock against an unrelated operator starting a backup.

A failed step stops immediately with `accepted: false` in `journal.json`.
There is no automatic rollback, ownership reset or cluster deletion. The
journal and any `PRIVATE-command-failure.txt` are private mode-0600 files;
**never upload the entire evidence directory**. Command failures can contain
credentials. Upload only the observer's sanitized fresh/handoff JSON and a
reviewed sanitized journal. The journal retains the failed stage before any
recovery; it does not equate recovery with accepted reversal.

An explicitly reviewed recovery may use a **new** evidence directory and the
original journal's exact DaemonSet UID:

```bash
python3 tests/velero-ownership/drive.py recover-local \
  --plan "$RUNNER_TEMP/owner-candidate/plan.json" \
  --daemonset-uid EXACT_ORIGINAL_UID \
  --evidence "$RUNNER_TEMP/owner-recovery"
```

Recovery recreates/verifies local config, detaches the protected Core agent,
transfers only a known owner, redeploys local, waits for the same UID, then
retires Core config. An unknown, terminating or incomplete resource stops it.
It records `recoveryOnly: true` and never sets acceptance true. Helpers are
idempotent only after checking current API objects; the full trial deliberately
refuses reusing an evidence directory or an existing fresh-install agent.

The manual-only `Staged migrations` workflow is implemented for review but has
not been dispatched. Its default selects Velero on native AMD; ARM-only
completes the other architecture later without repeating AMD. Main is required;
there are no automatic PR, push or scheduled triggers. The `identities` and
`all` selections also require the separately reviewed identity driver in the
same source commit. Missing driver/package/phase evidence fails before claiming
acceptance.
Use the same run's slim Core 1.16 bootstrap, local-path-local StorageClass and
warm published package, then this exact driver. Do not run the ordinary
install/upgrade matrix or unrelated monitoring/portal/Falco checks. If identity
is also selected, require owner acceptance plus the restored local/shared
baseline before its separate driver and keep separate scenario results. The owner driver wall is 180 minutes per selected architecture for bootstrap, staged deployments
and three 35-minute bounded backup/restore/API calls. This is a **ceiling, not
a measured runtime**; AMD pilot evidence must establish actual cost before
running ARM. Missing package/credentials, admission conflicts, bootstrap
failures or missing scenario proofs fail the job; no blanket retry or skipped
green summary. Both architectures' live acceptance remains required before any
default change or issue closure.

The workflow always publishes a newly generated public evidence directory,
including an explicit `accepted: false` receipt and allowlisted stage progress
on failure. It deeply filters observer JSON (numeric agent counters, fixed
owners/selectors, IDs, hashes and completed volume-copy identities), strips raw
controller messages and never recursively uploads a private trial directory.
The summary requires every selected architecture's accepted receipt to match
this exact source SHA, run and attempt. Owner acceptance requires the complete
ordered phase sequence and all three backup proofs, including positive evidence
that the old Core config is absent from both live API and stored manifest.
Recovery and baseline-only runs cannot count. Optional passive-watch output is
a separate diagnostic artifact, never a required-health or acceptance signal.

No-cluster format proof used UDS0.41 to create and inspect a 646-byte file-only
Zarf package and a 1.8-KiB OCI-layout bundle, verifying relative local-package
resolution, actual archive names and the OCI manifest digest. It pulled no
images/packages and deployed nothing. It does not validate the large Core
candidate's admission, SSA ownership behavior or actual restore paths.
