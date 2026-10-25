# Building the images

`uds run build-image` and `mise run build-image` both run [`.github/container-and-chart/docker/build.sh`](../.github/container-and-chart/docker/build.sh). GitHub Actions runs that same script from [`.github/workflows/container.yaml`](../.github/workflows/container.yaml), and only when files under `.github/container-and-chart/`, that workflow, or the `upstream/takserver` pin change.

## Where the source comes from

The TAK Server source is a git submodule at [`upstream/takserver`](../upstream/takserver), pinned to commit `5187abd46d827d37cfc5708805eced197a837e49`, which is the public tag `5.7-RELEASE-14` of [TAK-Product-Center/Server](https://github.com/TAK-Product-Center/Server). `.gitmodules` marks it shallow, so a clone fetches that one commit and no history.

```bash
git submodule update --init --depth 1 upstream/takserver
```

`build.sh` runs that command when the directory is empty. It refuses to build when the submodule is checked out at a different commit than the one this repository pins, or when it has local changes.

`build.sh` passes the submodule work tree to BuildKit as the `takserver-src` build context, with the commit and its tree id as build arguments. The builder stage copies the files, removes the submodule's `.git` pointer file, and commits them again as one commit tagged with the release. TAK's `src/build.gradle` reads its version from `git describe` and the branch name, so the war still reports `5.7-RELEASE-14-HEAD`, the same as a detached clone of the tag. The stage fails unless the tree id of that commit equals the upstream commit's tree id, which proves the files are exactly the pinned commit. The Ignite image copies `ignite.sh` from the same context instead of downloading it.

Renovate's `git-submodules` manager is on. `.gitmodules` sets `branch = 5.7-RELEASE-14`, so Renovate looks for newer `X.Y-RELEASE-N` tags and moves the pinned commit, the tag in `.gitmodules`, and the other `5.7-RELEASE-14` strings in one pull request. See [ADR 0008](../adr/0008-tak-source-as-a-submodule.md).

## Running the build

The host needs a container runtime. Docker Buildx is the supported one. It builds for the machine's architecture unless you set `PLATFORMS`.

```bash
./.github/container-and-chart/docker/build.sh
PLATFORMS=linux/amd64,linux/arm64 ./.github/container-and-chart/docker/build.sh
PUSH_IMAGES=true ./.github/container-and-chart/docker/build.sh
```

`CONTAINER_RUNTIME=podman` is a best-effort override. Podman is not what this repository tests. If `podman buildx` is missing, the script falls back to `podman build` for a single platform and stops if you asked for more than one.

You do not need a JDK, Gradle, protoc, or Node on the host. The Dockerfile's builder stage is Temurin 17.0.20, pinned by the image digest. Gradle is the upstream wrapper, 8.10.2. protoc 3.25.8 and the UI's Node downloads come from Gradle. The Gradle cache is a BuildKit cache mount at `/gradle`, so a rebuild on the same builder does not download everything again. In GitHub Actions that cache is also stored with the Actions cache.

The runtime stages use UBI9 OpenJDK 17, also pinned by the manifest-list digest, so the same pin covers amd64 and arm64. The Temurin builder digest is a manifest list with both as well.

The builder stays on Java 17. TAK Server 5.7-RELEASE-14, commit `5187abd46d827d37cfc5708805eced197a837e49`, is still the newest public tag. Its Gradle wrapper is 8.10.2, and that Gradle cannot run on Java 25: Groovy stops in the build script with `Unsupported class file major version 69`. TAK 5.7 targets Java 17, and the runtime image is OpenJDK 17, so `mise.toml` pins Temurin 17 as well. Moving the builder means a newer upstream wrapper, or a wrapper bump in this repository that still emits Java 17 bytecode and passes the install and upgrade tests.

The six tags match `zarf.yaml`:

- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-config:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-messaging:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-api:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-plugins:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-database-setup:5.7-RELEASE-14`
- `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-ignite:5.7-RELEASE-14`

Pull requests scan the loaded images with Grype and Trivy. A push of these files also writes SPDX SBOMs and can push the tags. A vulnerability report does not fail the workflow.

`takserver-tool-ui` uses `react-scripts` 5.0.1. Its ESLint setup names a `jest/globals` environment that the installed plugin does not provide, so the UI build stops before it writes the bundle. The builder sets `DISABLE_ESLINT_PLUGIN=true`. The upstream `package.json` is not changed.

## Docker Hub rate limits

The Zarf package pulls three images from `docker.io`: Postgres (`imresamu/postgis`), NATS (`library/nats:2.15.1-alpine`), and the NATS config reloader (`natsio/nats-server-config-reloader:0.25.0`). Docker Hub limits anonymous pulls per IP address, so a shared runner or sandbox can fail package creation with `429 toomanyrequests`. Pull them through a mirror:

```bash
uds run create-dev-package --set CREATE_OPTIONS="--registry-override docker.io=mirror.gcr.io"
```

The package still records the `docker.io` image names. Only the place Zarf pulls from changes.

## Architectures

The images are published for `linux/amd64` and `linux/arm64`. The container workflow does not use QEMU. It builds each architecture on a native GitHub runner (`ubuntu-24.04` and `ubuntu-24.04-arm`), each with its own Gradle and BuildKit cache. It pushes `<tag>-<key>-amd64` and `<tag>-<key>-arm64`. A last job runs [`merge-image-manifests.sh`](../.github/scripts/merge-image-manifests.sh), which joins them with `docker buildx imagetools create` into one index under `<tag>-<key>`. It writes nothing unless both per-architecture tags exist. `wait-for-tak-images.sh` checks that each index lists both platforms before a package or test job uses it.

### Tags keyed by the build inputs

- The inputs are the pinned `upstream/takserver` commit plus the git tree of `.github/container-and-chart/docker`, recorded in the `dev.uds-k3d-takserver.inputs` label. `<key>` is the first 12 hex digits of their SHA-256. `build.sh --tag` prints `5.7-RELEASE-14-<key>` for the current commit.
- The container workflow builds only when `5.7-RELEASE-14-<key>` is not already published for both architectures. A pull request that does not change those inputs reuses the images built for them before.
- `5.7-RELEASE-14` and `5.7-RELEASE-14-<arch>`, the tags in the committed files and in released packages, are written only from `main`, from the keyed images.
- `wait-for-tak-images.sh` waits for the keyed index, and `.github/scripts/pin-image-tags.sh` points `zarf.yaml`, `tasks.yaml` and `bundle/uds-config.yaml` at it before CI creates a package. A keyed tag only ever holds one set of inputs, so a pull request deploys its own TAK images even when another branch builds different ones at the same time.

To check a published tag:

```bash
docker buildx imagetools inspect ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-api:5.7-RELEASE-14
```

A local `build.sh` run builds the host architecture. `PLATFORMS=linux/amd64,linux/arm64` builds both with Buildx, which emulates the other architecture under QEMU and takes much longer. See [ADR 10](../adr/0010-amd64-and-arm64.md).
