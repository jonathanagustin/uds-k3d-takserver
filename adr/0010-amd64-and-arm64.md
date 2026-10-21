# 10. Build, package, and test for amd64 and arm64

Date: 2026-10-20

## Status

Accepted

## Context

The six TAK images were built for `linux/amd64` only, and the Zarf package, the test bundle, and the CI deploy all ran on amd64. Arm64 hosts are common for both development (Apple silicon laptops running k3d) and deployment (Graviton and other arm64 cloud nodes). UDS Core publishes `core-base` and the `k3d-core-slim-dev` checkpoint for both architectures, so the platform this package sits on already supports arm64.

Zarf packages are per architecture. A package carries one image per reference, pulled for the package's architecture, so an arm64 package needs every image it lists to have an arm64 variant.

The images and their bases:

- The builder (Temurin 17 on Ubuntu 22.04) and the runtime base (UBI9 OpenJDK 17) are manifest lists that include arm64.
- TAK's Gradle build already pulls the `linux-aarch_64` Netty epoll, tcnative, and QUIC natives, and the Node and protoc downloads have arm64 builds.
- NATS and its config reloader are multi-arch.
- `docker.io/postgis/postgis:15-3.4`, the image the upstream chart names, is amd64 only.

Building arm64 under QEMU on an amd64 runner emulates the whole Gradle and Node compile, which is many times slower than a native build. GitHub provides native `ubuntu-24.04-arm` runners for public repositories.

## Decision

- The container workflow builds each architecture on a native runner (`ubuntu-24.04` and `ubuntu-24.04-arm`) and pushes `<tag>-amd64` and `<tag>-arm64`. A final job joins them with `docker buildx imagetools create` into one index under `<tag>`, the tag `zarf.yaml` and the values reference. The merge refuses to write `<tag>` unless every architecture's tag exists, so it cannot replace a multi-arch index with fewer platforms.
- `wait-for-tak-images.sh` treats a tag as published only when its index lists `linux/amd64` and `linux/arm64`.
- Postgres uses `docker.io/imresamu/postgis:15-3.4`, the multi-arch build of the same `postgis/docker-postgis` Dockerfiles published by one of that project's maintainers. It has the same PostgreSQL 15.8 and PostGIS 3.4.3 as the amd64-only image, on Debian bookworm instead of bullseye.
- The package workflow creates the package on both architectures. The install test (k3d, slim UDS Core, the test bundle, SSO, and the full smoke and Playwright suite) runs on both. The release workflow publishes one package per architecture, each created on its own native runner.

## Consequences

- One image tag and one package reference work on either architecture. `zarf package deploy` and `uds deploy` pick the package for the cluster, or take `--architecture`.
- Every image change costs two native builds instead of one. They run in parallel.
- The Postgres image comes from a maintainer's namespace rather than the `postgis` organization. Switch back if `postgis/postgis` starts publishing arm64.
- The upgrade test stays on amd64 until a released arm64 package exists to upgrade from.
- Any image added to `zarf.yaml` must have an arm64 variant, or the arm64 package create fails. That failure is intended.
