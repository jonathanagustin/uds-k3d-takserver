# syntax=docker/dockerfile:1.28
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# PostgreSQL 18 with PostGIS 3.6.4 for amd64 and arm64.
#
# The base is the Docker Official postgres image on Debian bookworm, pinned by
# its index digest. PostGIS comes from the PostgreSQL project's packages,
# pinned by file checksum. An existing data directory is still PostgreSQL 15
# (the previous image, tag 15-3.4). The entrypoint runs pg_upgrade, so this
# image also installs the PostgreSQL 15 server and its PostGIS library. See
# adr/0018-upgrade-postgres-in-place.md.
ARG POSTGRES_IMAGE=postgres:18-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc

# The pgdg package version, URL encoded for the file names below. The same
# PostGIS upload is built for PostgreSQL 15 and 18.
ARG POSTGIS_DEB_VERSION=3.6.4%2Bdfsg-2.pgdg12%2B1

FROM scratch AS postgis18-deb-amd64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:c12fe97f4abd7bf021a0818fb72227409bca7c01cb1344c19afc402b6b386390 \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-18-postgis-3_${POSTGIS_DEB_VERSION}_amd64.deb /postgresql-18-postgis-3.deb

FROM scratch AS postgis18-deb-arm64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:f1949fbb6821264c0dfb9d10a58c719841c56b238a0f2ce8f78fa392b6861d21 \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-18-postgis-3_${POSTGIS_DEB_VERSION}_arm64.deb /postgresql-18-postgis-3.deb

FROM scratch AS postgis18-scripts-deb
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:002022de82d0b6f05e3366b339ff8d66b5f9d8df03f5050d42f5fdc60f80395f \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-18-postgis-3-scripts_${POSTGIS_DEB_VERSION}_all.deb /postgresql-18-postgis-3-scripts.deb

FROM scratch AS postgis15-deb-amd64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:382a1a005a669f80487896d945a28019defc8ad83cec3ad2018959a83e1d9ee3 \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3_${POSTGIS_DEB_VERSION}_amd64.deb /postgresql-15-postgis-3.deb

FROM scratch AS postgis15-deb-arm64
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:0e0cc91d9a182cea29b316b24d53c05cc4381b49a6453940791fd8576da3971a \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3_${POSTGIS_DEB_VERSION}_arm64.deb /postgresql-15-postgis-3.deb

FROM scratch AS postgis15-scripts-deb
ARG POSTGIS_DEB_VERSION
ADD --checksum=sha256:c7e617f8f97a411c25547649d6f161686a632f17eccf571171d003e40ada5f7f \
    https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgis/postgresql-15-postgis-3-scripts_${POSTGIS_DEB_VERSION}_all.deb /postgresql-15-postgis-3-scripts.deb

FROM ${POSTGRES_IMAGE}

ARG TARGETARCH
ARG INPUTS=""
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver

LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.title="postgis" \
      org.opencontainers.image.description="PostgreSQL 18 with PostGIS 3.6.4" \
      dev.uds-k3d-takserver.inputs="${INPUTS}"

# postgresql-15 is the server pg_upgrade uses for the old data directory. It is
# not checksum-pinned: any 15.x newer than the cluster can read it, and the
# base image's apt lists move. The PostGIS debs are pinned above. The official
# image already sets create_main_cluster = false, so this install does not
# create a second cluster.
RUN --mount=from=postgis18-deb-amd64,target=/debs/amd64/18 \
    --mount=from=postgis18-deb-arm64,target=/debs/arm64/18 \
    --mount=from=postgis18-scripts-deb,target=/debs/all/18 \
    --mount=from=postgis15-deb-amd64,target=/debs/amd64/15 \
    --mount=from=postgis15-deb-arm64,target=/debs/arm64/15 \
    --mount=from=postgis15-scripts-deb,target=/debs/all/15 \
    set -eux; \
    case "${TARGETARCH}" in amd64 | arm64) ;; *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        postgresql-15 \
        /debs/all/15/postgresql-15-postgis-3-scripts.deb \
        /debs/all/18/postgresql-18-postgis-3-scripts.deb \
        "/debs/${TARGETARCH}/15/postgresql-15-postgis-3.deb" \
        "/debs/${TARGETARCH}/18/postgresql-18-postgis-3.deb"; \
    rm -rf /var/lib/apt/lists/*

COPY 10_postgis.sh /docker-entrypoint-initdb.d/10_postgis.sh
COPY docker-entrypoint-upgrade.sh /usr/local/bin/docker-entrypoint-upgrade.sh

# Setting ENTRYPOINT drops the base image's CMD.
ENTRYPOINT ["docker-entrypoint-upgrade.sh"]
CMD ["postgres"]
