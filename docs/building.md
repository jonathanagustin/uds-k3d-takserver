# Building the images

`uds run build-image` and `mise run build-image` both run [`.github/container-and-chart/docker/build.sh`](../.github/container-and-chart/docker/build.sh). GitHub Actions runs that same script from [`.github/workflows/container.yaml`](../.github/workflows/container.yaml), and only when files under `.github/container-and-chart/` or that workflow change.

The host needs a container runtime. Docker Buildx is the supported one. It builds for the machine's architecture unless you set `PLATFORMS`.

```bash
./.github/container-and-chart/docker/build.sh
PLATFORMS=linux/amd64,linux/arm64 ./.github/container-and-chart/docker/build.sh
PUSH_IMAGES=true ./.github/container-and-chart/docker/build.sh
```

`CONTAINER_RUNTIME=podman` is a best-effort override. Podman is not what this repository tests. If `podman buildx` is missing, the script falls back to `podman build` for a single platform and stops if you asked for more than one.

You do not need a JDK, Gradle, protoc, or Node on the host. The Dockerfile's builder stage is Temurin 17.0.20, pinned by the image digest. Gradle is the upstream wrapper, 8.10.2. protoc 3.25.8 and the UI's Node downloads come from Gradle. The Gradle cache is a BuildKit cache mount at `/gradle`, so a rebuild on the same builder does not download everything again. In GitHub Actions that cache is also stored with the Actions cache.

The runtime stages use UBI9 OpenJDK 17, also pinned by the manifest-list digest, so the same pin covers amd64 and arm64. A private `ubuntu-latest` runner has 2 vCPU and 8 GB. The workflow's default platform is `linux/amd64` so the compile stays on one architecture. Pass `linux/amd64,linux/arm64` when the runner can spend the memory on a second compile.

The six tags match `zarf.yaml`:

- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-config:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-messaging:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-api:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-plugins:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-database-setup:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-ignite:5.7-RELEASE-14`

Pull requests scan the loaded images with Grype and Trivy. A push of these files also writes SPDX SBOMs and can push the tags. A vulnerability report does not fail the workflow.

`takserver-tool-ui` uses `react-scripts` 5.0.1. Its ESLint setup names a `jest/globals` environment that the installed plugin does not provide, so the UI build stops before it writes the bundle. The builder sets `DISABLE_ESLINT_PLUGIN=true`. The upstream `package.json` is not changed.
