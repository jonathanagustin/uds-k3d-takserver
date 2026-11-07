# 21. Velero node-agent for databases that outgrow a Secret

Date: 2026-10-25

## Status

Accepted

## Context

[ADR 0016](0016-logical-db-dump.md) stores `pg_dump` output in Secrets. A Secret holds about 1Mi, and the CronJob refuses a dump over 700000 bytes. Past that, the Postgres files have to be copied from the volume.

UDS Core 1.16.0 backup-restore, like 1.15.2, installs Velero v1.18.4 and does not deploy a node-agent. The image `velero/velero:v1.18.4` is already the one that package runs, and that tag publishes amd64 and arm64. File-system backup needs the agent on the node, with host access to `/var/lib/kubelet/pods`. k3d local-path still has no VolumeSnapshot API, so a snapshot is not the alternative.

The logical dump stays. The full-core deploy turns file-system backup on as well, and `tests/backup-restore.sh` checks that the Backup copied the Postgres volume. It still loads the dump after restore.

## Decision

- `FILESYSTEM_BACKUP` defaults to `false`. Slim leaves it there. `bundle/full/uds-config.yaml` sets it for the full-core job only.
- When it is `true`, the config chart renders DaemonSet `node-agent` in the `velero` namespace from `docker.io/velero/velero:v1.18.4`, and Exemption `velero-node-agent` for the host access that DaemonSet needs. The image is in this package so an air-gapped deploy has it.
- The same switch annotates the Bitnami Postgres pod volume `data` and the CloudTAK PostGIS pod volume `data` with `backup.velero.io/backup-volumes`. Velero then copies those volumes on the existing schedule. The schedule stays `snapshotVolumes: false`.
- The agent uses ServiceAccount `velero-server` (the Velero server's) and Secret `velero-bucket-credentials`, which `core-backup-restore` already creates. The pods carry `app.kubernetes.io/name: velero` so the Velero Package's storage egress rule matches them. The full bundle adds a Kubernetes API egress allow for `name: node-agent`.

## Consequences

- A default install is unchanged: no DaemonSet, no exemption, no volume annotation. The dump CronJobs and `tests/backup-restore.sh` stay the restore path.
- Setting the variable on a cluster that does not have the `velero` namespace leaves the DaemonSet unscheduled.
- The full-core job requires the node-agent to log `Starting controllers` and the Backup to hold a Completed copy of the Postgres `data` volume. Slim never deploys the agent.
- The agent is privileged. The exemption is limited to pods named `node-agent-*` in `velero`.

## Amendment: hostPath volumes

Velero skips hostPath PersistentVolumes in file-system backup, and k3d `local-path` makes hostPath PersistentVolumes by default. The TAK Postgres StorageClass is now `POSTGRES_STORAGE_CLASS`, empty by default so existing installs and their volume claim templates do not change. Full-core CI creates class `local-path-local` (`defaultVolumeType: local`) and installs Postgres on it, so the PodVolumeBackup check proves the agent copies the volume. File-system backup needs a Container Storage Interface (CSI) class or that variant on a new install. The gzipped logical dumps stay the backup that works everywhere.

The CloudTAK chart now has its own `CLOUDTAK_STORAGE_CLASS` variable. Full-core sets it to `local-path-local` on a new install, so Velero can also copy that volume. The default remains the cluster's default class; on k3d that is hostPath and Velero skips it. The `cloudtak-db-dump` Secret remains a backup in both cases.

## Amendment: data mover pods

Velero 1.18 copies each volume in a separate data-mover pod. The node-agent creates one for every PodVolumeBackup and PodVolumeRestore. `node-agent-config` sets `privilegedFsBackup: true`, because root without capabilities cannot open the Postgres data directory (mode 0700).

Those pod names change every backup. The Exemption custom resource definition (CRD) in UDS Core 1.16.0 rejects `matcher.podLabels`. So a second exemption entry matches every pod in the `velero` namespace, for five policies. It renders only when `FILESYSTEM_BACKUP=true`. See [Policy exemptions](../docs/justifications.md#velero-node-agent).

## Investigation: upstream chart ownership

Date: 2026-11-07. Follow-up: [issue 258](https://github.com/jonathanagustin/uds-k3d-takserver/issues/258).

Core 1.16.0 pins the upstream Velero chart to `12.2.1` in
[`src/velero/common/zarf.yaml`](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/src/velero/common/zarf.yaml).
That chart supports `deployNodeAgent: true`. Its `nodeAgent` values can reproduce
the existing agent's security context, resources, tolerations and extra args.
The chart already supplies `name: node-agent`, `role: node-agent`, the
`velero-server` ServiceAccount, credential mounts and kubelet host paths.

The candidate below is an addition to `core-backup-restore.overrides.velero.velero`
in the full bundle. It is a render experiment, not an applied bundle change.
Keep the existing `configuration.extraEnvVars` override that sets `HOME` to
`/scratch`; chart 12.2.1 passes that list to both the server and node-agent.

```yaml title="Candidate Velero chart overrides; not enabled"
values:
  - path: deployNodeAgent
    value: true
  - path: nodeAgent
    value:
      podSecurityContext:
        runAsUser: 0
        runAsGroup: 0
        runAsNonRoot: false
      containerSecurityContext:
        privileged: true
        runAsUser: 0
        runAsGroup: 0
        runAsNonRoot: false
      resources:
        requests:
          cpu: 25m
          memory: 128Mi
        limits:
          memory: 512Mi
      tolerations:
        - operator: Exists
      extraArgs:
        - --node-agent-configmap=velero-node-agent-config
  - path: configMaps.node-agent-config
    value:
      data:
        node-agent-config.json: >-
          {"privilegedFsBackup":true,"podLabels":{"app.kubernetes.io/name":"velero","app.kubernetes.io/component":"velero-data-mover"}}
```

The upstream chart prefixes its `configMaps` keys with the release fullname,
so this produces `velero-node-agent-config`, rather than the current
`node-agent-config`. The agent argument must use that generated name.
Core excludes node-agent security contexts from its package-values mapping;
the proposed settings are Helm bundle overrides on the `velero` chart, rather
than entries in the Core package-values file. Their passage through a complete
UDS bundle deployment still needs verification.

Local validation used Helm 4.3.1, chart 12.2.1, Core 1.16.0's common values and
the candidate values above. The Core bucket placeholders were replaced with
non-secret fixture strings for rendering. The rendered agent has the expected
ServiceAccount, role label, image `velero/velero:v1.18.4`, privilege, root user,
host paths, scratch environment and configuration argument. The generated
ConfigMap contains the privileged file-system backup and data-mover labels.
This confirms that the chart can express the workload. It does not prove
admission, backup, restore or Helm ownership transfer on a cluster.

Keep the current owner until a staged migration is tested:

1. Make the host-access Exemption available before Core enables its agent.
   The full bundle currently deploys `core-backup-restore` before the TAK
   package, which owns the Exemption. A fresh install must not wait for the
   privileged agent to become Ready before its required Exemption exists.
2. Handle the existing `node-agent` DaemonSet's Helm release ownership. Core
   cannot simply create an object already owned by `uds-takserver-config`.
   A migration must also prevent the old release from deleting the agent
   during its next upgrade. Test this with an existing install, not only an
   empty cluster.
3. Remove the local DaemonSet and `node-agent-config` only after the new chart
   owns their replacements. Keep the volume annotations and the Exemption.
4. Run Full Core backup and restore on both architectures, requiring Completed
   PodVolumeBackup and PodVolumeRestore objects and the post-restore API smoke
   check. Confirm slim still deploys neither the agent nor its Exemption.

The ownership change remains open in issue 258. No production override or
Helm ownership metadata was changed by this investigation.
