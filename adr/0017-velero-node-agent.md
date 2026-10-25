# 17. Velero node-agent for databases that outgrow a Secret

Date: 2026-10-25

## Status

Accepted

## Context

[ADR 0016](0016-logical-db-dump.md) stores `pg_dump` output in Secrets. A Secret holds about 1Mi, and the CronJob refuses a dump over 700000 bytes. Past that, the Postgres files have to be copied from the volume.

UDS Core 1.15.2 backup-restore installs Velero v1.18.4 and does not deploy a node-agent. The image `velero/velero:v1.18.4` is already the one that package runs, and that tag publishes amd64 and arm64. File-system backup needs the agent on the node, with host access to `/var/lib/kubelet/pods`. k3d local-path still has no VolumeSnapshot API, so a snapshot is not the alternative.

The logical dump stays. The full-core deploy turns file-system backup on as well, and `tests/backup-restore.sh` checks that the Backup copied the Postgres volume. It still loads the dump after restore.

## Decision

- `FILESYSTEM_BACKUP` defaults to `false`. Slim leaves it there. `bundle/full/uds-config.yaml` sets it for the full-core job only.
- When it is `true`, the config chart renders DaemonSet `node-agent` in the `velero` namespace from `docker.io/velero/velero:v1.18.4`, and Exemption `velero-node-agent` for the host access that DaemonSet needs. The image is in this package so an air-gapped deploy has it.
- The same switch annotates the Bitnami Postgres pod volume `data` and the CloudTAK PostGIS pod volume `data` with `backup.velero.io/backup-volumes`. Velero then copies those volumes on the existing schedule. The schedule stays `snapshotVolumes: false`.
- The agent uses ServiceAccount `velero` and Secret `velero-bucket-credentials`, which `core-backup-restore` already creates. The pods carry `app.kubernetes.io/name: velero` so the Velero Package's storage egress rule matches them. The full bundle adds a Kubernetes API egress allow for `name: node-agent`.

## Consequences

- A default install is unchanged: no DaemonSet, no exemption, no volume annotation. The dump CronJobs and `tests/backup-restore.sh` stay the restore path.
- Setting the variable on a cluster that does not have the `velero` namespace leaves the DaemonSet unscheduled.
- The full-core job requires the node-agent to log `Starting controllers` and the Backup to hold a Completed copy of the Postgres `data` volume. Slim never deploys the agent.
- The agent is privileged. The exemption is limited to pods named `node-agent-*` in `velero`.
