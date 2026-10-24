# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# Browser view of the ATAK test device: ws-scrcpy (MIT) streams the screen over
# the device's adb connection, and phone.html frames it. Remote shell and file
# listing are compiled out. amd64 only, like the device VM.

ARG NODE_IMAGE=node:20.20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

FROM ${NODE_IMAGE} AS source
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
ARG WS_SCRCPY_REF=986eaecdba2d3d8b59bf040cbee420fc46a46be9
RUN git init -q /src && cd /src \
    && git fetch -q --depth 1 https://github.com/NetrisTV/ws-scrcpy.git "${WS_SCRCPY_REF}" \
    && git checkout -q FETCH_HEAD
WORKDIR /src
COPY atak/viewer/build.config.override.json build.config.override.json
# The generated dist/package.json pins express 4.18.3, ws 8.16.0 and yaml
# 2.4.1, which have published advisories. Raise them inside the same major
# versions before the runtime install.
RUN npm ci --no-audit --no-fund && npm run dist \
    && cd dist && npm pkg set dependencies.express=4.22.3 dependencies.ws=8.22.0 dependencies.yaml=2.9.1

# The dist step writes its own package.json with no lockfile. The runtime
# dependencies come from dist-package-lock.json, so they are pinned by
# integrity hash. npm ci fails when that file no longer matches, for example
# after a WS_SCRCPY_REF change. Regenerate it with:
#   docker buildx build -f atak/viewer/Dockerfile --target dist-lock \
#     --output type=local,dest=atak/viewer .
#   mv atak/viewer/package-lock.json atak/viewer/dist-package-lock.json
FROM source AS lock
RUN cd dist && npm install --omit=dev --package-lock-only --no-audit --no-fund

FROM scratch AS dist-lock
COPY --from=lock /src/dist/package-lock.json /package-lock.json

FROM source AS build
COPY atak/viewer/dist-package-lock.json dist/package-lock.json
RUN cd dist && npm ci --omit=dev --no-audit --no-fund

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
