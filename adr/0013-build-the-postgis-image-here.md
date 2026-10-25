# 13. Build the PostGIS image in this repository

Date: 2026-10-21

## Status

Accepted. Replaces the Postgres image decision in [ADR 10](0010-amd64-and-arm64.md). The PostgreSQL 15 and PostGIS 3.4.3 pin is superseded by [ADR 18](0018-upgrade-postgres-in-place.md). Building the image in this repository still stands.

## Context

TAK's Postgres and CloudTAK's database both ran `docker.io/imresamu/postgis:15-3.4`. [ADR 10](0010-amd64-and-arm64.md) chose it because the official `postgis/postgis` image is amd64 only and the package supports arm64. It is built from the `postgis/docker-postgis` Dockerfiles by one of that project's maintainers, but it is published in a personal Docker Hub namespace, not by the PostGIS project, and the reference is pinned by tag only.

That image was also a Docker Hub dependency at package build time. Docker Hub rate-limits anonymous pulls per IP address, so a shared runner or sandbox could not create the package (`429 toomanyrequests`).

Checked on 2026-10-21, every official `postgis/postgis` tag for PostgreSQL 15 to 17 still lists amd64 only, and so does `ghcr.io/cloudnative-pg/postgis`. The Docker Official `postgres` image is multi-arch. The PostgreSQL project's apt repository carries PostGIS for amd64 and arm64, but keeps only the newest builds (3.6.x); 3.4.3 builds are in `apt-archive.postgresql.org`.

## Decision

- Build the image here from `postgres:15-bookworm`, pinned by index digest, with PostGIS 3.4.3 from the PostgreSQL project's packages. The three package files (amd64, arm64 and the shared scripts package) are fetched from `apt-archive.postgresql.org` and verified by sha256 in the Dockerfile.
- Keep PostgreSQL 15 and PostGIS 3.4.3. A database that already has the extension needs no `ALTER EXTENSION postgis UPDATE`. The previous image was PostgreSQL 15.8, this one is the current 15.x patch release of the base.
- Use the same init script behavior as before: `template_postgis`, and `postgis`, `postgis_topology`, `fuzzystrmatch` and `postgis_tiger_geocoder` in it and in `$POSTGRES_DB`.
- Build and publish it the way the CloudTAK image is built: each architecture on a native runner as `15-3.4-<arch>`, joined into `15-3.4` by `build.sh --merge`, with `build.sh --wait` in the workflows that read it. The inputs label is the git tree of `.github/container-and-chart/postgis`.

## Consequences

- No third-party image in the package, and no Docker Hub pull for Postgres at package build time.
- Changing the PostgreSQL major version or the PostGIS version is a deliberate change in this directory, with the data migration it needs, not a tag bump.
- The PostGIS package files come from an archive host. A change to or removal of those files fails the build at the checksum, which is the intended behavior.
- The two NATS images are still pulled from Docker Hub at package build time. They are official images, but mirroring them to GHCR would remove the last Docker Hub dependency.
- Renovate updates the `postgres` base digest. The PostGIS package pins are changed by hand.
