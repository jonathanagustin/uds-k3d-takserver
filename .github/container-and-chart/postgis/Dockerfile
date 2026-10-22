# syntax=docker/dockerfile:1.7
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# PostgreSQL 15 with PostGIS 3.4.3 for amd64 and arm64.
#
# The base is the Docker Official postgres image on Debian bookworm, pinned by
# its index digest. PostGIS comes from the PostgreSQL project's own packages
# (pgdg), pinned by file checksum. apt.postgresql.org keeps only the newest
# PostGIS builds, and 3.4.3 is in apt-archive.postgresql.org. The checksums
# make a changed or replaced file fail the build.
#
# Changing PostGIS on a database that already has the extension needs
# ALTER EXTENSION postgis UPDATE, so keep 3.4.3 until that is planned.
ARG POSTGRES_IMAGE=postgres:15-bookworm@sha256:22c6356b2897cb0b4be6ad550b44ff97a0f29df7dbe327c01bc3c84bd457694d

# The pgdg package version, URL encoded for the file names below.
ARG POSTGIS_DEB_VERSION=3.4.3%2Bdfsg-2.pgdg120%2B1

FROM scratch AS postgis-deb-amd64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:a50f5816417e616f7b70aa7b16970027e069418f2d2c82c6cbd871a67d76f3a8 \
    https://apt-archive.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3_${POSTGIS_DEB_VERSION}_amd64.deb /postgresql-15-postgis-3.deb

FROM scratch AS postgis-deb-arm64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:16046df1f80783da10469e4571538c6638e965648e3c7975f5d8a09e8265fe37 \
    https://apt-archive.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3_${POSTGIS_DEB_VERSION}_arm64.deb /postgresql-15-postgis-3.deb

FROM scratch AS postgis-scripts-deb
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:d6a4f3e7d3d99f32558f110ca73d7b459eb7d6747c620826991c96cb250978d4 \
    https://apt-archive.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3-scripts_${POSTGIS_DEB_VERSION}_all.deb /postgresql-15-postgis-3-scripts.deb

FROM ${POSTGRES_IMAGE}

ARG TARGETARCH
ARG INPUTS=""
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver

LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.title="postgis" \
      org.opencontainers.image.description="PostgreSQL 15 with PostGIS 3.4.3" \
      dev.uds-k3d-takserver.inputs="${INPUTS}"

# Both architectures' packages are mounted, because a mount cannot name a
# stage with a variable. The shell picks the one for this build. The postgis
# package depends on the scripts package at the same version, and on libraries
# (GDAL, GEOS, PROJ and others) that bookworm provides.
RUN --mount=from=postgis-deb-amd64,target=/debs/amd64 \
    --mount=from=postgis-deb-arm64,target=/debs/arm64 \
    --mount=from=postgis-scripts-deb,target=/debs/all \
    set -eux; \
    case "${TARGETARCH}" in amd64 | arm64) ;; *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        /debs/all/postgresql-15-postgis-3-scripts.deb \
        "/debs/${TARGETARCH}/postgresql-15-postgis-3.deb"; \
    rm -rf /var/lib/apt/lists/*

COPY 10_postgis.sh /docker-entrypoint-initdb.d/10_postgis.sh
