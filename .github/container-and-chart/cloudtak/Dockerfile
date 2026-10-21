# syntax=docker/dockerfile:1.7
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
RUN npm prune --omit=dev

# Same base tag as upstream's Dockerfile, pinned by digest. Renovate updates
# the digest when the tag moves. Alpine packages still float, as upstream.
FROM nginx:alpine3.24@sha256:892bb2152464f0c5d8972593a5f5afaf8054552580b699d95f8ff4af08c2d33d
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
