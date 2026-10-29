# syntax=docker/dockerfile:1.28
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# CloudTAK, built from the upstream/cloudtak submodule.
#
# `cloudtak-upstream` is CloudTAK's own Dockerfile built from that submodule
# with no changes (see docker-bake.hcl). That image keeps the compilers, the
# web app's node_modules, and the API's dev dependencies it built with, about
# 2.2 GB. This file copies the built API and web app onto the same nginx
# base with only the runtime packages, and changes how the container starts:
# nginx and node run as the image's nginx user (uid 101), and every file
# written at runtime goes under /tmp, so the pod can run with a read-only
# root filesystem.
# hadolint ignore=DL3006
FROM cloudtak-upstream AS built
# The API's package.json lists tsx and drizzle-kit as dependencies, and
# @openaddresses/batch-generic names drizzle-kit as a peer, so npm keeps
# them after the prune. The API runs the compiled dist/index.js with plain
# node and applies its migrations through drizzle-orm, so nothing loads them
# at runtime. Between them they carry three esbuild Go binaries, which image
# scanners report for the Go standard library they were built with. Remove
# them, and fail the build if an esbuild binary is left.
RUN npm prune --omit=dev \
 && rm -rf node_modules/tsx node_modules/drizzle-kit node_modules/esbuild \
      node_modules/@esbuild node_modules/@esbuild-kit \
      node_modules/.bin/tsx node_modules/.bin/drizzle-kit node_modules/.bin/esbuild \
 && left="$(find node_modules -type f -name esbuild)" \
 && if [ -n "${left}" ]; then \
      echo "esbuild is still in the API's node_modules: ${left}" >&2; exit 1; \
    fi

# Same base tag as upstream's Dockerfile, pinned by digest. Renovate updates
# the digest when the tag moves. Alpine packages still float, as upstream.
FROM nginx:alpine3.24@sha256:785835ea65db4bba6f021acc0f3be91b0fef76a53fe41f8588c6698d2aed0606
# hadolint ignore=DL3018
RUN apk add --no-cache bash nodejs-current openssl
COPY --from=built /home/etl/api /home/etl/api
COPY --from=built /home/etl/app/dist /home/etl/app/dist

ARG CLOUDTAK_VERSION
ARG UPSTREAM_SHA
LABEL org.opencontainers.image.title="cloudtak" \
      org.opencontainers.image.description="CloudTAK browser map client built from github.com/dfpc-coe/CloudTAK" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${CLOUDTAK_VERSION}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.source="https://github.com/jonathanagustin/uds-k3d-takserver"

COPY --chmod=0755 start.sh /home/etl/uds/start.sh
COPY --chmod=0644 bootstrap.mjs basemap.mjs /home/etl/uds/
COPY --chmod=0644 nginx-sso.conf nginx-sso-head.conf /home/etl/uds/
# Next to dist/ and node_modules/ so its imports resolve like CloudTAK's.
COPY --chmod=0644 sso.mjs /home/etl/api/uds-sso.mjs

ENV HOME=/tmp
WORKDIR /home/etl/api
USER 101:101
CMD ["/home/etl/uds/start.sh"]
