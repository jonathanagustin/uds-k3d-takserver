# Back up and restore TAK Server

Create a Velero backup with fresh logical database dumps, then load those dumps
after restoring the namespaces into a recovery environment.

## What you'll accomplish

Recover the TAK and CloudTAK database contents and the existing TAK certificate
authority (CA), so enrolled clients can reconnect with their certificates.

## Prerequisites

- A full UDS Core deployment with Velero, an available backup storage location,
  and access to its backup bucket from the recovery environment. Slim core does
  not include Velero.
- `kubectl`, the UDS CLI, and a Velero CLI compatible with the installed server.
- This repository checked out for `tests/db-dump-secret.sh`.
- `backup.dump.enabled: true` on both application charts, as in
  [`bundle/full/uds-bundle.yaml`](../../bundle/full/uds-bundle.yaml).

## Before you begin

Check the current Kubernetes context and arrange a maintenance window. Stop
application writes before the two dumps if you need a consistent recovery point
across TAK and CloudTAK. Record replica counts and the deployed package version.

> [!WARNING]
> A backup contains private keys, keystores, and database credentials. Protect
> the bucket and recovery environment as you protect the running cluster.
> Load logical dumps into fresh databases, not databases that already contain
> application data. Do not delete a working namespace to try this procedure.

Check storage coverage in [Data](../data.md#backup). A hostPath volume is skipped
by Velero even when the node-agent runs. Keep logical dumps for both databases;
if either gzipped dump exceeds 700000 bytes, verify a volume backup and its
restore before relying on it. The namespace backup does not replace a backup of
UDS Core, Keycloak, or separately managed `TakClient` resources in `takclients`.

## Steps

1. Confirm the backup destination is available:

   ```bash title="Check Velero storage"
   kubectl get backupstoragelocations.velero.io -n velero
   ```

   The location used by the backup must have phase `Available`.

2. Refresh both dump Secrets and wait for both Jobs to complete:

   ```bash title="Refresh logical dumps"
   BACKUP="tak-manual-$(date +%s)"
   kubectl create job -n takserver "${BACKUP}" --from=cronjob/tak-db-dump
   kubectl create job -n cloudtak "${BACKUP}" --from=cronjob/cloudtak-db-dump
   kubectl wait -n takserver --for=condition=Complete "job/${BACKUP}" --timeout=6m
   kubectl wait -n cloudtak --for=condition=Complete "job/${BACKUP}" --timeout=6m
   ```

   Stop if a Job fails. Its old dump Secret is not proof of a fresh backup.

3. Back up the application namespaces and inspect the result:

   ```bash title="Back up the application namespaces"
   velero backup create "${BACKUP}" --include-namespaces takserver,cloudtak --wait
   velero backup describe "${BACKUP}" --details
   ```

   Require phase `Completed`, inspect warnings, and confirm the dump and
   certificate Secrets are included. When relying on file-system backup, also
   require Completed PodVolumeBackups for the database `data` volumes.

4. In a recovery environment with compatible UDS Core, storage, package images,
   and access to the same bucket, select the backup by name. The application
   namespaces must be absent or prepared by your recovery plan. Restore it:

   ```bash title="Restore the application namespaces"
   velero restore create "${BACKUP}-restore" --from-backup "${BACKUP}" --wait
   velero restore describe "${BACKUP}-restore" --details
   ```

   Require `Completed` and review warnings before continuing. Pause application
   writers while loading logical dumps:

   ```bash title="Pause database writers"
   kubectl scale -n takserver deployment/takserver-api deployment/takserver-messaging deployment/takserver-plugins deployment/takserver-config --replicas=0
   kubectl scale -n cloudtak deployment/cloudtak --replicas=0
   kubectl rollout status -n takserver statefulset/takserver-postgresql --timeout=10m
   kubectl rollout status -n cloudtak statefulset/cloudtak-postgis --timeout=10m
   ```

   Confirm the application pods have terminated before loading data. Scaling
   requests their termination; it does not wait for their database connections
   to close. Keep the database pods running.

5. If the volumes came back empty, recreate the recovery databases before
   loading the logical dumps: a restored application may have initialized
   tables before you paused it. Do not do this to databases recovered from a
   volume backup or to the original running deployment. These commands delete
   the named databases in the selected recovery context:

   ```bash title="Recreate databases only in the recovery environment"
   kubectl exec -n takserver takserver-postgresql-0 -- psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS cot WITH (FORCE);' -c 'CREATE DATABASE cot;'
   kubectl exec -n cloudtak cloudtak-postgis-0 -- psql -U cloudtak -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS cloudtak WITH (FORCE);' -c 'CREATE DATABASE cloudtak;'
   ```

   Load the dumps in Bash with `pipefail`:

   ```bash title="Load logical dumps into fresh databases"
   set -o pipefail
   tests/db-dump-secret.sh takserver tak-db-dump | kubectl exec -i -n takserver takserver-postgresql-0 -- psql -U postgres -d cot -v ON_ERROR_STOP=1
   tests/db-dump-secret.sh cloudtak cloudtak-db-dump | kubectl exec -i -n cloudtak cloudtak-postgis-0 -- psql -U cloudtak -d cloudtak -v ON_ERROR_STOP=1
   ```

   The helper reads `dump.sql.gz` and also accepts the older `dump.sql` key.
   If a pipeline fails, leave writers stopped and inspect the error.

6. Restore the recorded replica counts. For the default single-replica install:

   ```bash title="Resume the application"
   kubectl scale -n takserver deployment/takserver-api deployment/takserver-messaging deployment/takserver-plugins deployment/takserver-config --replicas=1
   kubectl scale -n cloudtak deployment/cloudtak --replicas=1
   kubectl rollout status -n takserver deployment/takserver-api --timeout=15m
   kubectl rollout status -n takserver deployment/takserver-messaging --timeout=15m
   kubectl rollout status -n cloudtak deployment/cloudtak --timeout=10m
   ```

## Verification

Sign in to TAK and CloudTAK, read a record known to exist before the backup, and
connect an already enrolled client. Confirm its CA still matches the restored
server. A Completed API-object backup alone does not prove database recovery.

On a disposable full-core test cluster, `tests/backup-restore.sh` verifies marker
rows, namespace restoration, and an API call using a certificate saved before
the restore. It **deletes both application namespaces**; use it only for that
destructive test, not as a backup command for a running deployment.

## Troubleshooting

### The dump Job fails

**Problem:** There is no fresh logical dump.

**Symptom:** The Job is failed or logs report a dump larger than 700000 bytes.

**Solution:** Read the Job's init-container logs. Resolve database access or
use a verified file-system backup when the Secret size limit is reached. Do
not continue with a stale Secret.

### Velero copies no database volume

**Problem:** The backup contains Kubernetes objects but no database files.

**Symptom:** The volume is hostPath, or no Completed PodVolumeBackup exists.

**Solution:** Restore the logical dump. For future volume backups, use supported
storage and enable `FILESYSTEM_BACKUP`; storage class changes require a planned
migration or a new install.

## Related documentation

- [Data and backup contents](../data.md#backup)
- [Logical dump decision](../../adr/0016-logical-db-dump.md)
- [Velero node-agent decision](../../adr/0021-velero-node-agent.md)
