# Upgrade from 0.6 to 0.7

Migrate PostgreSQL and certificates from 0.6 to 0.7. Verify that existing data
and client identities survive.

## What you'll accomplish

Upgrade the package with UDS Core 1.16.0, migrate the existing PostgreSQL 15
volumes to PostgreSQL 18, and keep the deploy-time CA and enrolled clients.

## Prerequisites

- An existing 0.6 deployment and permission to upgrade its UDS bundle.
- The UDS CLI and `kubectl`, with the intended cluster context selected.
- A tested recovery plan for both database volumes and certificate Secrets.
- A selected, signed 0.7 release, verified using [Verify a release](../../README.md#verify-a-release).

## Before you begin

Record the deployed versions, database PVC names, CA fingerprint, and a known
database record. Arrange downtime: database migration and TAK restarts interrupt
clients. Snapshot both database volumes or export `pg_dumpall` from each
PostgreSQL 15 pod and keep the dumps outside the cluster. Preserve the original
certificate objects as described in [Backup](../data.md#backup).

> [!WARNING]
> `pg_upgrade --link` shares the old table files with PostgreSQL 18. Once the new
> server writes to them, changing the image tag back does not roll back the
> database. Rollback requires the pre-upgrade volume snapshot or a database
> restored from the pre-upgrade dump.

## Steps

1. Upgrade UDS Core to 1.16.0 before the application, or include Core and TAK in
   one bundle that orders Core first. The Pepr module uses the controller image
   supplied by Core. Use [the test bundle](../../bundle/uds-bundle.yaml) as an
   ordering reference and retain your deployment's configuration.
2. Set the TAK package reference in your bundle to the selected
   `0.7.<patch>-upstream` release, with its keyless verification block. Keep
   existing PVCs and storage classes. `FILESYSTEM_BACKUP` defaults to `false`
   and `POSTGRES_STORAGE_CLASS` defaults to empty; do not change the StatefulSet
   volume claim templates as part of this upgrade.
3. Deploy the updated bundle through your normal signed bundle process. If Core
   has already been upgraded and the passthrough gateway is enabled, you can
   also deploy the package directly:

   ```bash title="Deploy the selected 0.7 package"
   VERSION=0.7.0 # Replace with the verified 0.7 patch selected for this upgrade.
   uds zarf package deploy "oci://ghcr.io/jonathanagustin/uds-k3d-takserver/takserver:${VERSION}-upstream" --confirm
   ```

   The 0.7 release retains the registry namespace used before the repository rename.

   Pass `--architecture amd64` or `--architecture arm64` when the target differs
   from the deployment host. Each database pod runs its own migration on first
   start; its startup probe allows ten minutes for that first start.
4. Wait for the database and TAK rollouts. Do not delete a PVC or interrupt a
   running `pg_upgrade` to make the rollout faster. Read the database logs if a
   rollout stalls.

## Verification

Check both databases:

```bash title="Check the TAK database version"
kubectl exec -n takserver takserver-postgresql-0 -- psql -U postgres -d cot -c 'SHOW server_version_num;' -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis';"
```

```bash title="Check the CloudTAK database version"
kubectl exec -n cloudtak cloudtak-postgis-0 -- psql -U cloudtak -d cloudtak -c 'SHOW server_version_num;' -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis';"
```

Expect PostgreSQL major version 18 and PostGIS 3.6. Confirm the PVC names and
known records are unchanged, then connect an enrolled client and sign in to
CloudTAK. The certificate Job moves private keys and keystores out of
`cert-migration` into Secrets `takserver-certs` and `takserver-ca-key` while
retaining the CA. An existing install retains its old keystore password; the
random password applies to new installs.

If dump CronJobs are enabled, their new dumps use key `dump.sql.gz`. The restore
helper still accepts a 0.6 Secret containing `dump.sql`.

## Troubleshooting

### The database does not become ready

**Problem:** A database rollout stops during migration.

**Symptom:** The database container exits or reports a failed `pg_upgrade`.

**Solution:** Read that container's logs and preserve its volume. The entrypoint
supports PostgreSQL 15 and 18 data directories only. Recover using the
pre-upgrade snapshot or dump if the migration cannot complete; never start the
PostgreSQL 15 image against data already written by PostgreSQL 18.

### The Pepr module cannot start

**Problem:** The application upgraded before compatible Core components.

**Symptom:** The module cannot use its expected controller image.

**Solution:** Check Core was upgraded to 1.16.0 and that the bundle installs Core
before TAK. Follow [CI workflows](../ci.md) for the automated upgrade checks;
the PostgreSQL 15 baseline job uses release 0.6.0 explicitly.

## Related documentation

- [PostgreSQL migration details](../data.md#upgrading-from-postgresql-15)
- [Certificate handling](../configuration.md#certificates)
- [PostgreSQL in-place upgrade decision](../../adr/0018-upgrade-postgres-in-place.md)
