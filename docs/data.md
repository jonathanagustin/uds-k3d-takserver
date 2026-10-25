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

`k3d-core-slim-dev` installs `core-base` and `core-identity-authorization`. It does not install Velero. The standard UDS Core package has an optional `velero` component and the S3 settings for it. This package does not enable that component and does not ship a `Backup` or `Schedule`.

A restore of TAK needs the Postgres volume (database `cot`) and ConfigMap `cert-migration`. The ConfigMap holds the CA and server keystores generated at deploy time. Without those files, enrolled client certificates no longer chain to the server. CoreConfig and the Ignite ConfigMap are in git and can be re-rendered. When the standard core package enables Velero, the backup should include the `takserver` namespace. That puts the Postgres PVC and `cert-migration` in the backup.

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
