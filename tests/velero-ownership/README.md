# Opt-in Velero ownership experiment

This is an experimental preparation and **read-only** acceptance harness for
[issue 258](https://github.com/jonathanagustin/uds-takserver/issues/258), not a
production migration command. It never transfers metadata, upgrades Helm,
deletes namespaces or initiates a restore. FILESYSTEM_BACKUP remains false by
default and FILESYSTEM_BACKUP_OWNER remains local. A direct switch on an
existing installation can delete the current agent and configuration.

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

## Proposed ephemeral Full Core trial, pending review

Reuse the existing Full Core workflow's native two-architecture jobs and warm
published images; do not add app image compilation or a parallel cold matrix.
No workflow or dispatch is added by this preparation. Run on one reviewed
candidate commit after normal gates settle, with an explicit timeout and bounded
sanitized artifacts. Stage operations in each disposable job:

1. **Existing local path:** install the ordinary full bundle first. Install the
   candidate's equivalent bootstrap exemption through core-base before enabling
   Core's privileged agent. Observe local-before. Save external recovery state
   privately: both Helm histories/manifests, DS UID/resourceVersion/managedFields
   and the old config. These are not public workflow artifacts.
2. A separately reviewed one-off driver must protect the DS, transfer only the
   expected local Helm owner using UID/resourceVersion/old-owner preconditions,
   enable the candidate Core chart and new config, verify Ready agents, then
   upgrade TAK with owner=core. Observe core-ready; perform the existing backup,
   volume restore and post-restore API acceptance; observe core-after.
3. Reverse in controlled order: retain bootstrap, recreate the real local
   ConfigMap before local rollout, protect the DS while removing it from Core's
   manifest, transfer ownership only after exact precondition checks, deploy the
   local agent, then retire Core's config after local readiness. Observe
   local-ready; run a new backup/restore/API acceptance; observe local-after.
4. Exercise interruption boundaries and unknown-owner refusal before declaring
   this an operator migration. Raw rollback of either release independently is
   not a demonstrated recovery procedure. Do not run namespace deletion or
   metadata restoration as an unconditional cleanup handler.
5. On a **separate fresh ephemeral cluster**, deploy candidate core-base/Core
   agent before TAK owner=core, observe fresh-ready and require fresh-core
   backup/restore/API acceptance. This may reuse the same native job after its
   prior disposable cluster is explicitly removed, rather than adding jobs.

This preparation does not contain the mutating driver: its exact Zarf commands,
metadata preconditions, stop/recovery paths and admission/field-manager behavior
still need review and live validation. Thus a standard green Full Core run or
these offline tests alone cannot close issue 258. The live matrix must prove
both architectures and the staged paths above before any default-owner change.

Local preparation host: Docker 29.9.2 answers, zero containers/volumes, but only
about 1.6 GiB filesystem space was free. A real local Full Core deployment was not
attempted; unrelated cache data was not deleted to force it to fit.

Offline checks (no cluster, downloads or ownership writes):

```bash
uv run --no-project --with pyyaml==6.0.3 python -B -m unittest \
  tests.test_filesystem_backup_owner tests.test_velero_handoff -v
```
