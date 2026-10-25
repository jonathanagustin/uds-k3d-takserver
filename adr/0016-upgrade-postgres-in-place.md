# 16. Upgrade Postgres in place

Date: 2026-10-25

## Status

Accepted. Supersedes the PostgreSQL 15 and PostGIS 3.4.3 pin in [ADR 13](0013-build-the-postgis-image-here.md). Building the image in this repository still stands.

## Context

The PostGIS image was `postgres:15-bookworm` with PostGIS 3.4.3, published as `15-3.4`. PostgreSQL 18 is the current major. A PostgreSQL 18 server will not open a PostgreSQL 15 data directory, and `tests/upgrade.sh` deploys the last release (still 15), writes a row, and checks that the row and the PVC survive an in-place upgrade.

TAK and CloudTAK use the same image and different directories. The Bitnami chart sets `PGDATA=/bitnami/postgresql/data` and runs the container as uid 1001. CloudTAK sets `PGDATA=/var/lib/postgresql/data/pgdata` and runs as uid 999. The official PostgreSQL 18 image also moved its own default data directory to `/var/lib/postgresql/18/docker`. Both of our charts set `PGDATA`, so that default is not the path on the volume.

PostGIS 3.4 is not built for PostgreSQL 18. The PostgreSQL project's bookworm packages currently publish PostGIS 3.6.4 for 15 and for 18.

## Decision

- Publish the new image as `18-3.6`: PostgreSQL 18 and PostGIS 3.6.4, from checksum-pinned pgdg packages, on `postgres:18-bookworm` pinned by index digest. Leave `15-3.4` in the registry. This workflow no longer rebuilds it.
- Install the PostgreSQL 15 server and PostGIS 3.6.4's PostgreSQL 15 library in the same image. The entrypoint, `docker-entrypoint-upgrade.sh`, runs only when the container is starting `postgres` and `PG_VERSION` is 15. It reads the locale from `template0`, runs `initdb` for 18 with that locale, then `pg_upgrade --link`, then `postgis_extensions_upgrade()` in each database that has PostGIS. It then deletes the old directory and execs the official entrypoint.
- A data directory that is already 18 starts unchanged. Any other major makes the container exit. An empty directory is a new cluster: the official entrypoint and `10_postgis.sh` create it.
- Give the TAK Postgres startup probe and the CloudTAK Postgres startup probe ten minutes. `pg_upgrade` finishes before the server listens, and the liveness probe would otherwise kill the pod.
- Rollback is a volume snapshot, or a `pg_dumpall` taken before the rollout, restored onto `15-3.4`. `--link` shares the table files, so the old directory is gone after a successful start and cannot be booted with PostgreSQL 15.

## Consequences

- The first start of `18-3.6` on a 15 volume is the migration. TAK and CloudTAK migrate separately, each when its pod starts.
- The upgrade test checks the row, its timestamp, the PVC, `server_version_num` of at least 180000, and PostGIS 3.6.
- A database large enough that `pg_upgrade` exceeds ten minutes needs a higher `startupProbe.failureThreshold` before the rollout.
- Renovate can keep updating the `postgres:18-bookworm` digest. A further major still needs a migration.
