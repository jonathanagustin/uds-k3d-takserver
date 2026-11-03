# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# Browser view of the ATAK test device: ws-scrcpy (MIT) streams the screen over
# the device's adb connection, and phone.html frames it. Remote shell and file
# listing are compiled out. amd64 only, like the device VM.

# The build stages compile ws-scrcpy's development dependencies, and its
# node-pty 0.10.1 native addon does not build on Node 26 (ATAK device VM run
# 41707626016) or Node 24 (run 41709858736). They stay on Node 22 LTS
# (supported to 2027-04-30). node-pty only backs the adb shell, which is
# compiled out, and is not in dist-package-lock.json: the runtime dependencies
# are plain JavaScript, so the image that ships runs Node 26 LTS.
ARG BUILD_NODE_IMAGE=node:22.23-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
ARG NODE_IMAGE=node:26.13-bookworm-slim@sha256:bc0a2afd3b74ce12222fc8bab99271e66257f021078f5f4a5d687a77d280c1d9

FROM ${BUILD_NODE_IMAGE} AS source
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
# Scorecard flags this `npm install` as an unpinned npm command. The stage
# does not install packages into an image that ships. It writes
# dist/package-lock.json from the package.json the source stage just
# edited, so a maintainer can refresh atak/viewer/dist-package-lock.json
# (`docker build --target dist-lock`). The runtime stage below installs
# with `npm ci`, which checks that lockfile. `npm ci` cannot create it.
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
