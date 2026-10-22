# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# Browser view of the ATAK test device: ws-scrcpy (MIT) streams the screen over
# the device's adb connection, and phone.html frames it. Remote shell and file
# listing are compiled out. amd64 only, like the device VM.

ARG NODE_IMAGE=node:20.20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

FROM ${NODE_IMAGE} AS build
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
ARG WS_SCRCPY_REF=986eaecdba2d3d8b59bf040cbee420fc46a46be9
RUN git init -q /src && cd /src \
    && git fetch -q --depth 1 https://github.com/NetrisTV/ws-scrcpy.git "${WS_SCRCPY_REF}" \
    && git checkout -q FETCH_HEAD
WORKDIR /src
COPY atak/viewer/build.config.override.json build.config.override.json
RUN npm ci --no-audit --no-fund && npm run dist \
    && cd dist && npm install --omit=dev --no-audit --no-fund

FROM ${NODE_IMAGE}
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends adb ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build --chown=1000:1000 /src/dist /app/dist
COPY --chown=1000:1000 atak/viewer/phone.html /app/dist/public/phone.html
COPY atak/viewer/entrypoint.sh /usr/local/bin/entrypoint.sh
ENV HOME=/tmp
USER 1000
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
