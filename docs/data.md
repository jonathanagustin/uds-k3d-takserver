# Data

## Postgres

The upstream TAK chart installs Bitnami PostgreSQL in the `takserver` namespace. This package does not replace that database.

| Setting | Value |
| --- | --- |
| Service | `takserver-postgresql` |
| Port | 5432 |
| Database | `cot` |
| User | `postgres` |
| Password | the upstream example value `postgres` |
| JDBC | `jdbc:postgresql://takserver-postgresql:5432/cot` in `CoreConfig.xml` |
| Image | `ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:15-3.4` (amd64 and arm64) |

The chart also renders ConfigMap `postgres-configuration`. `pg_hba.conf` and `postgres.conf` are empty because the chart has no `extras/` files for them. Postgres uses the Bitnami chart defaults.

The password is not a production secret. Replace it, and the matching JDBC password, before a shared cluster.

## Backup

Slim (`k3d-core-slim-dev`) does not install Velero. The full bundle does. `core-backup-restore` at `1.15.2-upstream` is a required package there, not an optional component. See [ADR 0016](../adr/0016-logical-db-dump.md).

Velero's default schedule is `velero-udsbackup`, daily at 03:00 UTC, TTL 240h, `snapshotVolumes: false`. UDS Core 1.15.2 does not ship the node agent, and k3d local-path has no snapshot API, so the backup is API objects only. The Postgres files on the volume are not in it. The package stores a logical `pg_dump` in Secret `tak-db-dump` (database `cot`) and Secret `cloudtak-db-dump` (CloudTAK's PostGIS database). CronJobs `tak-db-dump` (02:15 UTC) and `cloudtak-db-dump` (02:20 UTC) refresh those Secrets. They render only when `backup.dump.enabled` is true, which the full bundle sets. A slim install does not create them.

What a namespace backup contains:

| Object | In the backup |
| --- | --- |
| ConfigMap `cert-migration` | Yes. It holds the CA and the server keystores, including private keys, because that is the object the upstream chart mounts. A restored server presents the same CA. |
| Secret `cloudtak-tak-admin` and the Keycloak client Secrets | Yes. They are namespace objects. |
| Secrets `tak-db-dump` and `cloudtak-db-dump` | Yes, when the CronJob or `tests/backup-restore.sh` has written them. |
| Postgres and PostGIS volumes | No. Load the dump after the pods are back. |
| Ignite | No. The cache is memory. Clients reconnect. |
| CoreConfig and the Ignite ConfigMap | Yes, as rendered objects. The chart can render them again from git. |

A Secret holds about 1Mi. The CronJob refuses a dump over 700000 bytes. A database that large needs a node-agent image and file-system backup, which this package does not add.

Restore, after Velero has put the namespaces back:

1. Scale the TAK API, messaging, plugins, and config Deployments to 0, and scale CloudTAK to 0, so they do not write during the load.
2. Wait until `takserver-postgresql` and `cloudtak-postgis` are Ready.
3. Load `tak-db-dump` into database `cot` and `cloudtak-db-dump` into database `cloudtak`. The volumes came back empty.
4. Scale the Deployments to 1. Enrolled client certificates still chain, because `cert-migration` came back with the namespace.

`tests/backup-restore.sh` does this at the end of the full-core job. It writes table `uds_restore_marker` in both databases, requires Backup `Completed` and Restore `Completed`, reads the marker back, and runs `tests/api-smoke.sh` with the client certificate copied out before the namespaces were deleted. The checkpoint MinIO is scaled to 0 by `fit-runner`; the script scales it back to 1 because Velero's default bucket `uds` is on that MinIO. BackupStorageLocation has to be `Available`.

## Find TAK logs

`k3d-core-slim-dev` does not install Vector or Loki. The per-PR tests check TAK startup on container stdout and stop there. A cluster with the `core-logging` layer ships that stdout to Loki. Query it through `loki-gateway` (port 80, API on `/loki`).

TAK startup, from the API process:

```logql
{namespace="takserver"} |= "Started TAK Server"
```

`TAK Server version` and `Tomcat started on port` are the same startup stream. Keep a line filter on this selector. `{namespace="takserver"}` alone is mostly Postgres, and a limit of a few hundred lines returns checkpoints before it returns the API startup line.

CloudTAK writes two lines of its own. `bootstrap.mjs` logs `ok - TAK user` after it creates the TAK user. `basemap.mjs` logs `basemap:` when it writes the tile proxy.

```logql
{namespace="cloudtak"} |= "ok - TAK user"
```

```logql
{namespace="cloudtak"} |= "basemap:"
```

A streaming client is logged by messaging. The callsign is the text after `to`. Substitute the device callsign. The disconnect line carries the subscription id, not the callsign.

```logql
{namespace="takserver"} |= "Set client for subscription" |= "CALLSIGN"
```

```logql
{namespace="takserver"} |= "Removed Subscription"
```

`/logs/takserver-api-access.log`, `/logs/takserver-db-audit.log`, and `/logs/takserver-esapi.log` are file-only. They are not in these queries. The test tasks print `Loki returned TAK logs`, `Loki returned CloudTAK logs`, and `Loki returned the streaming client callsign` when `core-logging` is installed. The client line is the callsign recorded by `tests/api-smoke.sh`.
