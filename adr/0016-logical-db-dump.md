# 16. Logical database dump, not a volume snapshot

Date: 2026-10-25

## Status

Accepted

## Context

A restore of TAK needs database `cot` and ConfigMap `cert-migration`. CloudTAK needs its PostGIS database and Secret `cloudtak-tak-admin`. `cert-migration` holds the CA and the server keystores from deploy time. Without those files, a client certificate issued before the backup no longer chains to the server.

UDS Core `1.15.2` backup-restore installs Velero v1.18.4 with the AWS and Azure plugins. It does not ship a node-agent image. File-system backup needs that agent, plus host access that this package would have to exempt. The default schedule `velero-udsbackup` runs at 03:00 UTC with `snapshotVolumes: false`. k3d local-path has no VolumeSnapshot API, so a backup copies API objects and leaves the Postgres files on the node.

`values/common-values.yaml` is input to the upstream TAK chart. That chart does not have a place to store a logical dump, and a Velero hook on its Postgres pod cannot write a Secret. The pod has no API client and no Role for one.

A Secret is about 1Mi. A fresh CI database fits. A long-lived TAK database may not.

## Decision

- Capture `cot` and the CloudTAK database with `pg_dump`, and store each dump in a Secret (`tak-db-dump`, `cloudtak-db-dump`). Velero backs those Secrets up with the namespace. File-system backup is not used.
- The CronJobs, their Roles, and their network rules render only when `backup.dump.enabled` is true. The default is false, so a slim install is unchanged when Velero is absent. `bundle/full/uds-bundle.yaml` turns the switch on. `test-values.yaml` does not, because the slim bundle uses that file too.
- The CronJobs run at 02:15 and 02:20 UTC, before the default Velero schedule. A dump over 700000 bytes fails the job instead of writing a Secret that will not fit.
- `tests/backup-restore.sh` runs at the end of `test:full-core`. It writes marker table `uds_restore_marker`, dumps both databases, runs a Backup of `takserver` and `cloudtak`, deletes those namespaces, runs a Restore, loads the dumps back because the volumes were not in the backup, reads the marker, and runs `tests/api-smoke.sh` with the client certificate copied out before the delete.
- The full-core job scales the checkpoint MinIO Deployment back to 1 for that test. `fit-runner` had scaled it to 0. Velero's default bucket is `uds` on that MinIO. BackupStorageLocation has to be `Available` or the test fails.
- In-memory Ignite state is not backed up. CoreConfig and the Ignite ConfigMap are rendered again from the chart.

## Consequences

- Slim stays free of dump CronJobs and of Velero. The full bundle requires `core-backup-restore`.
- A database that outgrows a Secret needs a node-agent image for both arches and a file-system backup exemption. This package does not add that image.
- The restore test deletes the TAK and CloudTAK namespaces. It is the last command in `test:full-core`.
- Whether Backup and Restore reach `Completed` on the GitHub runners is visible only after the full-core workflow runs.
