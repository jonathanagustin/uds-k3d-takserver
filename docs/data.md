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

`k3d-core-slim-dev` is `core-base`. It does not install Velero. The standard UDS Core package has an optional `velero` component and the S3 settings for it. This package does not enable that component and does not ship a `Backup` or `Schedule`.

A restore of TAK needs the Postgres volume (database `cot`) and ConfigMap `cert-migration`. The ConfigMap holds the CA and server keystores generated at deploy time. Without those files, enrolled client certificates no longer chain to the server. CoreConfig and the Ignite ConfigMap are in git and can be re-rendered. Velero, when the standard core package enables it, should include the `takserver` namespace so the Postgres PVC and `cert-migration` are in the backup.
