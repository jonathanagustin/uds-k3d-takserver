# uds-k3d-takserver

TAK Server packaged for [UDS](https://docs.defenseunicorns.com/core/) on a local k3d cluster.

The config chart renders, both Helm charts lint, and CI creates the package on every pull request. The install test (`uds run test-install`) deploys the bundle onto `k3d-core-slim-dev` in GitHub Actions. Anything that needs a live cluster outside CI is listed under TODO.

## Prerequisites

- Docker, with room for a local Kubernetes cluster. Podman can build images (`CONTAINER_RUNTIME=podman`) but that path is best-effort and is not what this repository tests. The [UDS local demo guide](https://docs.defenseunicorns.com/core/getting-started/local-demo/basic-requirements/) asks for at least 4 CPU, 10 GiB RAM, and 40 GiB disk for the container runtime. The overlay asks for 1Gi for config and 1536Mi for the API. Messaging copies the API limit. The test bundle applies `values/test-values.yaml` (512Mi request for config, the API, and Ignite, 640Mi for messaging, 1536Mi API and messaging limit, 1280Mi Ignite limit, 512m heap) so a private `ubuntu-latest` runner (2 vCPU, 8 GB) has a chance. The slim bundle still wants most of that memory. Set the repository variable `TEST_RUNNER` if the job needs a larger runner.
- [k3d](https://k3d.io/), used by the slim dev bundle and by `uds run cleanup`.
- UDS CLI, which includes Zarf. Homebrew:

  ```bash
  brew tap defenseunicorns/tap && brew install uds
  uds version
  ```

  Install notes: [UDS CLI installation](https://docs.defenseunicorns.com/cli/getting-started/installation/).

  Or install the pinned versions of k3d, UDS CLI, Helm, jq, Java, and the scan tools from [`mise.toml`](./mise.toml):

  ```bash
  mise install
  ```

  Docker is not in that file.

The cluster comes from the published slim bundle, which brings up k3d plus Istio, Keycloak, and Pepr:

```bash
uds deploy k3d-core-slim-dev:latest --confirm
```

That bundle does not select `istio-passthrough-gateway`. The test bundle upgrades `core-base` `1.15.0-upstream` and selects that component so the Package routes can bind.

## Upstream chart

The chart is the public repo [TAK-Product-Center/Server](https://github.com/TAK-Product-Center/Server), tag `5.7-RELEASE-14`, path `src/takserver-cluster/deployments/helm`. `common/zarf.yaml` points at that URL. The chart is not copied into this repository. Zarf clones it when the package is created. The repo is public, so that clone does not need extra git credentials.

Chart version in that tag is `4.5.0`. It has no `values.yaml`. The examples are `developer-values.yaml` and `production-values.yaml`. Dependencies, fetched by Helm at template time and not vendored here:

- Bitnami PostgreSQL `12.1.6`
- Ignite `2.17.0` from the chart's `third-party/ignite`
- NATS `1.0.1`

The upstream README says the release must be installed in the namespace `takserver`. The Helm release name is pinned to `takserver`.

`values/common-values.yaml` is the overlay used for the render. The chart's nginx ingress stays off (`takserver.ingress.enabled: false`). UDS exposes the same ports through the passthrough gateway.

## Images

`TAK_IMAGE_TAG` defaults to `5.7-RELEASE-14`. The TAK images are built from the upstream source and published under this repository. The package does not build them. [`uds run build-image`](./docs/building.md) does, and CI runs the same script. The names match the roles in the upstream chart:

| Image | Why it is listed |
| --- | --- |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-api:<tag>` | API Deployment |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-messaging:<tag>` | Messaging Deployment |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-config:<tag>` | Config Deployment |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-plugins:<tag>` | Plugins Deployment |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-database-setup:<tag>` | Post-install database setup Job |
| `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-ignite:<tag>` | Ignite StatefulSet |
| `docker.io/postgis/postgis:15-3.4` | Bitnami PostgreSQL image from the upstream example |
| `docker.io/library/nats:2.9.21-alpine` | NATS server rendered by the NATS chart |
| `docker.io/natsio/nats-server-config-reloader:0.11.0` | NATS config reloader rendered by the NATS chart |

Build them locally with Docker Buildx. The script is the same one CI runs. Pins, platforms, and the Gradle cache are in [`docs/building.md`](./docs/building.md).

```bash
uds run build-image
# or:
mise run build-image
# or:
./.github/container-and-chart/docker/build.sh
```

The host does not need a JDK. `PUSH_IMAGES=true` pushes to GHCR. Until that push has happened, `uds run create-dev-package` cannot pull the six tags.

```bash
uds run create-dev-package --set TAK_IMAGE_TAG=5.7-RELEASE-14
```

That create path has not been run from this environment.

## Package create in CI

`.github/workflows/lint.yaml` runs `hk check` and calls `uds-common` `callable-lint` at `v1.32.1`. `hk.pkl` runs yamllint, shellcheck (scripts plus the shared shell task over tasks, workflows, and Zarf actions), hadolint, actionlint, codespell, `lint:renovate`, `lint:helm`, `lint:helm-template`, `lint:zarf-tools`, `zarf dev lint` for the upstream flavor, and gitleaks plus a file check that reject `*.key`, `*.p12`, and `*.jks`. `RUN_LICENSE_CHECKS` is `true`. `uds run lint:all` checks SPDX headers for `GPL-3.0-only`. Lint does not clone the TAK chart or pull images.

`.github/workflows/container.yaml` builds the images with buildx bake when files under `.github/container-and-chart/` change. The six targets share one Gradle builder. A restored Gradle home is seeded into that build and saved again with `actions/cache`. Pull requests scan those images with Grype, one database update and then the six scans together. CVE diffs against the last release are posted by `.github/workflows/scan.yaml`, which calls `callable-scan` (`uds-pk scan compare`). A push of the images writes SPDX SBOMs. The release package SBOM is the one Zarf writes with Syft during `publish-package` (that create does not pass `--skip-sbom`). Keyless Cosign signing is optional and stays off: `.github/workflows/cosign.yaml` runs only from `workflow_dispatch` when `sign` is set. The default platform is `linux/amd64`.

`.github/workflows/test.yaml` runs `install` and `upgrade` for the `upstream` flavor as two jobs. They do not depend on each other. Upgrade runs only when `check-flavor` finds that flavor on the latest tag. Documentation-only pulls are ignored. When the Docker inputs are unchanged, the images job checks the six tags once and does not wait on a container rebuild. Install runs `uds run test-install`. Both paths deploy `k3d-core-slim-dev` from `.cache/k3d-core-slim-dev` when that package is already there, then `create:test-bundle`, `deploy:test-bundle`, `setup:keycloak-user`, and `test:all`. The slim package and `~/.zarf-cache` are restored with `actions/cache` at `v4.2.3`. The runner is `ubuntu-latest` (2 vCPU, 8 GB on a private repository) unless the repository variable `TEST_RUNNER` names a larger runner. On that runner the job deletes dotnet, Android, GHC, and CodeQL, and does not prune Docker images. `values/test-values.yaml` requests 512Mi for config, the API, and Ignite, and 640Mi for messaging. Config's limit stays 1Gi. The API limit is 1536Mi, and messaging copies that limit. Ignite's limit is 1280Mi with `-Xmx512m`. A failed test prints `kubectl top pods`, the node allocatable, and each container `lastState`. The checkpoint also needs a kernel with `vxlan` and the `xt_multiport` netfilter module. GitHub-hosted runners have both. A kernel without them cannot start `k3d-core-slim-dev`.

`.github/workflows/codeql.yaml` analyzes JavaScript/TypeScript and GitHub Actions. `.github/workflows/dependency-review.yaml` reviews pull request dependencies. `.github/workflows/scorecard.yaml` calls the shared OpenSSF Scorecard workflow on the default branches. A private repository needs `SCORECARD_READ_TOKEN` for that job. `.github/workflows/test-eks.yaml`, `test-rke2.yaml`, and `test-aks.yaml` are manual dispatch only and do nothing unless `enabled` is set. They need cloud credentials this repository does not have. OpenTofu 1.13.1 is pinned in `mise.toml`.

`.github/workflows/package.yaml` runs on pull requests (except image-only changes) and when started by hand. It asks GHCR whether the six TAK images exist at `5.7-RELEASE-14`, using the built-in `GITHUB_TOKEN` (`contents: read` and `packages: read`). If any manifest is not HTTP 200, the job prints a notice and succeeds without creating a package. When all six are present, it logs in to `ghcr.io` as `GITHUB_ACTOR` and runs `uds run create-dev-package`. The token is not printed. The chart repo is public, so the job does not configure git credentials.

## Quickstart

From this directory, once the six images exist:

```bash
uds run --list
uds run build-image       # six images from the public source
uds run create-dev-package
uds run dev               # package and bundle onto an existing cluster
uds run test-install      # new k3d-core-slim-dev cluster, Keycloak user, then validation
uds run lint:all          # shared yaml, shell, zarf, helm, and license checks
hk check                  # yamllint, shellcheck, hadolint, actionlint, codespell, renovate, helm, zarf, gitleaks
uds run cleanup           # delete the k3d cluster and local tarballs
```

`uds run default` creates the package, deploys `k3d-core-slim-dev` from the local package cache when that tarball is present, deploys the bundle, and runs validation. `uds run test-upgrade` installs the latest published package and then this branch. There is no published package yet, so upgrade has nothing to pull. `uds run publish-package` creates, tests, and publishes. `.github/workflows/release.yaml` calls the shared publish workflow for the `upstream` flavor on `amd64`.

`uds run dev` rebuilds the bundle and deploys it onto the cluster that is already up. `uds run test-install` deploys a new `k3d-core-slim-dev` cluster from the cached checkpoint, or pulls that checkpoint when the cache is empty.

## Architecture

`k3d-core-slim-dev` is installed first. The test bundle then upgrades `core-base` with `istio-passthrough-gateway` and deploys the `takserver` package.

A `helm template` of tag `5.7-RELEASE-14` with `values/common-values.yaml` (tag substituted to `5.7-RELEASE-14`) renders these Services in namespace `takserver`:

- `takserver-api-service`, selector `app: takserver-api`. Ports 8443, 8444, 8446. This package adds Service `takserver-web` on 8447 because the upstream Service does not.
- `takserver-messaging-service`, selector `app: takserver-messaging`. Ports 8089, 9000, 9001.
- `takserver-postgresql` on 5432 (Bitnami, database `cot`, user `postgres`). The password in the overlay is the upstream example value `postgres`. It is not a production secret.
- `takserver-ignite`, pod label `app: takserver-ignite`. The Ignite chart and the TAK client processes use the Kubernetes IP finder. The upstream chart sets their ServiceAccount to `takserver-ignite`. The Package allows the Ignite, API, messaging, config, and plugins pod labels to reach the Kubernetes API.
- `takserver-nats` and `takserver-nats-headless`. The overlay sets one replica, turns clustering off, and disables the NATS toolbox. The upstream developer example uses three replicas.

`chart/templates/prereqs.yaml` creates ConfigMaps `core-config` and `tak-ignite-config`, and Secret `reg-cred`. A pre-install Job in that chart runs TAK's `generateClusterCerts.sh` in the `takserver-config` image and creates ConfigMap `cert-migration` when it is missing. The same Job publishes ConfigMap `ignite-extensions` from the `ignite-extensions.jar` that the image build produces with the upstream Gradle task `:takserver-cluster:igniteExtensions`. The Ignite server needs TAK's classes from that jar. Zarf installs that chart before the upstream chart. The upstream chart mounts those ConfigMaps and always sets `imagePullSecrets` to `reg-cred`. `core-config` is the cluster example with the Postgres URL, user, and password already filled in, because the chart mounts `CoreConfig.xml` read-only. When `sso.enabled` is true, that file has one OpenID discovery element whose secret is `${TAK_OIDC_CLIENT_SECRET}`. After Helm, an init container runs `envsubst` and writes `/conf/CoreConfig.xml`, which TAK reads first. The keystore password is the upstream example value `atakatak`. The upstream chart does render `postgres-configuration`, but that ConfigMap's `pg_hba.conf` and `postgres.conf` keys are empty because the chart has no `extras/` files for them. See [docs/configuration.md](docs/configuration.md), [docs/networking.md](docs/networking.md), and [docs/sso.md](docs/sso.md).

The operator wires the cluster from the UDS `Package` rendered by `chart/`:

- Tenant gateway for the browser, and passthrough for certificates and streaming:
  - `https://takserver.uds.dev` on the tenant gateway to `takserver-web` port 8447
  - `https://takserver.uds.dev` on the passthrough gateway to `takserver-api-service` port 8446
  - `https://takserver-api.uds.dev` to `takserver-api-service` port 8443
  - `https://takserver-stream.uds.dev` to `takserver-messaging-service` port 8089
- Ports 8444, 9000, and 9001 stay on the Services and are not given gateway hosts.
- A Keycloak OIDC client, `uds-takserver`, Secret `takserver-sso`, redirect `https://takserver.uds.dev/login/redirect`. An init container writes the client secret into `CoreConfig.xml`. Authservice is not used.
- Default-deny with intra-namespace traffic (TAK processes, Postgres, Ignite, and NATS share the namespace), Kubernetes API egress for Ignite and the TAK clients that discover it, and tenant-gateway egress from the API selector for the Keycloak issuer.
- A `uds-trust-bundle` ConfigMap. The upstream chart does not mount it.

```text
browser
  -> tenant gateway (HTTPS on 443, host takserver.<domain>)
    -> Service/takserver-web:8447

TAK client
  -> Istio passthrough gateway (SNI)
    -> Service/takserver-api-service:8446 and :8443
    -> Service/takserver-messaging-service:8089
      -> Service/takserver-postgresql:5432
      -> Service/takserver-ignite
      -> Service/takserver-nats:4222

UDS operator
  -> Keycloak client uds-takserver (Secret takserver-sso, envsubst into CoreConfig on start)
  -> NetworkPolicy from the Package allow list
```

ATAK clients usually dial port 8089 on the server host. The passthrough gateway publishes that listener as SNI on port 443 (`takserver-stream.uds.dev`). Nothing here maps external port 8089.

## Sign in

Browser login is TAK's own OpenID Connect client, not Authservice.

1. Open `https://takserver.<domain>/` (tenant gateway, port 443). On the test cluster that host is `https://takserver.uds.dev/`.
2. TAK redirects to `https://sso.<domain>/realms/uds`.
3. Sign in as a user in `/UDS Core/Admin`. The test user is `doug`. TAK treats that group as `ROLE_ADMIN` and opens `/Marti/`.
4. Groups under `/TAK/` with a `_READ` or `_WRITE` suffix become TAK groups. `/TAK/Operators_READ` is group `Operators`.

`GET /Marti/api/util/user/roles` returns `ROLE_ADMIN`. `GET /Marti/api/groups/all` returns the mapped groups. TAK has no route named whoami.

Enrollment for a bearer token is `POST /Marti/api/tls/signClient/v2` on the 8446 passthrough host. The CSR common name must be the Keycloak username. See [Single sign-on](docs/sso.md).

## ATAK and WinTAK

8443 and 8089 require a client certificate. The passthrough gateway does not terminate TLS, so the client presents the certificate to TAK.

| Use | Host | Port on the gateway |
| --- | --- | --- |
| Admin UI with a certificate | `takserver-api.<domain>` | 443, SNI, service port 8443 |
| Streaming (ATAK / WinTAK) | `takserver-stream.<domain>` | 443, SNI, service port 8089 |
| Enrollment | `takserver.<domain>` on the passthrough gateway | 443, SNI, service port 8446 |

On k3d, host port 443 is the tenant gateway. Point the streaming and certificate hosts at the passthrough port-forward (the test uses 18443) or at a load balancer in front of `passthrough-ingressgateway`.

The deploy-time Job writes the CA and `admin.pem` into ConfigMap `cert-migration`. Import the CA into the TAK client trust store. For a user certificate, either use `admin.pem` for an admin device or enroll on 8446 with the bearer token from the browser session. Do not commit those files. See [Data](docs/data.md) for the database and for what a Velero backup of this namespace has to include.

## Repository tooling

Renovate config extends the public `defenseunicorns/uds-common` preset at `config/renovate.json5`. It groups support dependencies and package dependencies the same way the reference package does, and it has extra matchers for `mise.toml`, concrete `zarf.yaml` image tags, the `5.7-RELEASE-14` upstream tag, image digests, and Action SHAs. Renovate does not run until the Mend Renovate GitHub App is installed on this repository.

Pull request titles use conventional commits. `.github/workflows/commitlint.yaml` calls the shared commitlint workflow from `uds-common` `v1.32.1`. `hk.pkl` is the pre-commit config: after `mise install`, run `hk install` once. Playwright lives in `tests/` and uses pnpm. `auth.setup.ts` signs in to the Keycloak account console as the user `setup:keycloak-user` creates. `sso.spec.ts` signs that user in through TAK's OAuth redirect on `https://takserver.uds.dev/`, checks `ROLE_ADMIN` and the mapped group, and enrolls a certificate on 8446 with the bearer token. The UI test opens the Marti admin shell on the 8443 host with the admin client certificate. `tests/api-smoke.sh` checks the Marti API on 8443, 8447, 8446, and 8089. `test:all` runs it after install and after upgrade. There is no separate TypeScript helper, so there is no Vitest project. `uds run build-image` uses Docker Buildx unless `CONTAINER_RUNTIME` is set. Podman is best-effort.

`release-please-config.json` opens a release pull request when conventional commits land on `main` or `takserver-scaffold`. The tracked version starts at `0.1.0` in `chart/Chart.yaml`.

## Layout

| Path | Purpose |
| --- | --- |
| `zarf.yaml` | Package metadata, `DOMAIN`, `TAK_IMAGE_TAG`, image list |
| `common/zarf.yaml` | Config chart plus the upstream git chart (tag `5.7-RELEASE-14`) |
| `chart/files/` | CoreConfig and Ignite files the upstream chart mounts. Certificates are generated at deploy time |
| `chart/` | Helm chart that renders the UDS `Package` |
| `values/` | Overlay for the upstream chart, including `test-values.yaml` |
| `bundle/uds-bundle.yaml` | Test bundle: passthrough gateway plus this package |
| `bundle/uds-config.yaml` | Deploy-time `DOMAIN` and `TAK_IMAGE_TAG` |
| `tasks.yaml` | `uds run` tasks. Shared tasks come from `defenseunicorns/uds-common` `v1.32.1` |
| `tasks/test.yaml` | Health, mesh, policy, gateway, smoke, API smoke, and Playwright checks |
| `tests/` | API smoke script and pnpm Playwright: Keycloak setup, Marti admin shell, 8443 and 8446 |
| `docs/` | Configuration, networking, SSO, and image build notes |
| `adr/` | Architecture decision records |
| `.github/workflows/lint.yaml` | `hk check` and shared `callable-lint` |
| `.github/workflows/package.yaml` | `uds run create-dev-package` when the six GHCR images exist |
| `.github/workflows/container.yaml` | Image build, Grype, and image SBOMs on push |
| `.github/workflows/test.yaml` | `upstream` install and upgrade, in parallel |
| `.github/workflows/scan.yaml` | Grype CVE diff against the last release via `uds-pk` |
| `.github/workflows/codeql.yaml` | CodeQL for Actions and JavaScript/TypeScript |
| `.github/workflows/scorecard.yaml` | OpenSSF Scorecard |
| `.github/workflows/dependency-review.yaml` | GitHub dependency review on pull requests |
| `.github/workflows/cosign.yaml` | Optional keyless signing, off unless dispatched |
| `.github/workflows/test-eks.yaml` | Manual EKS scaffold, disabled by default |
| `.github/workflows/test-rke2.yaml` | Manual RKE2 scaffold, disabled by default |
| `.github/workflows/test-aks.yaml` | Manual AKS scaffold, disabled by default |
| `.github/test-infra/` | OpenTofu scaffolds for EKS, RKE2, and AKS |
| `.github/workflows/release.yaml` | Shared `callable-publish` for `upstream` `amd64`, with the Zarf Syft SBOM |
| `.github/container-and-chart/docker/` | Multi-stage Dockerfile and `build.sh` |
| `.github/workflows/commitlint.yaml` | Conventional-commit check for pull request titles |
| `.github/workflows/release-please.yaml` | Release pull request from conventional commits |
| `renovate.json` | Renovate, extending the public uds-common preset |
| `hk.pkl` | Pre-commit checks |
| `mise.toml` | Pinned k3d, UDS CLI, Helm, hk, OpenTofu, pnpm, codespell, Grype, and syft |
| `CODEOWNERS` | Review owners |
| `SECURITY.md` | How to report a vulnerability |

The layout follows the public [UDS package guide](https://docs.defenseunicorns.com/core/how-to-guides/packaging-applications/create-uds-package/) and the [uds-packages/template](https://github.com/uds-packages/template) / [reference-package](https://github.com/uds-packages/reference-package) repos: root `zarf.yaml`, shared `common/zarf.yaml`, a config chart, `values/`, `bundle/uds-bundle.yaml`, and `tasks.yaml`.

## Verified

- `yamllint .`
- `helm lint chart` and `helm template takserver chart --namespace takserver`
- `helm template` of [TAK-Product-Center/Server](https://github.com/TAK-Product-Center/Server) tag `5.7-RELEASE-14`, path `src/takserver-cluster/deployments/helm`, with `values/common-values.yaml` and the tag substituted to `5.7-RELEASE-14`. The chart is not in this repo. The render produced the Services, labels, and images listed above, with no empty template values
- `mise install` from `mise.toml`: k3d 5.9.0, UDS CLI 0.39.0, Helm 3.22.1, uv 0.13.1, yamllint 1.38.0. No cluster was created

## TODO

- Run `.github/workflows/container.yaml` on the default branch so the six `ghcr.io/jonathanagustin/uds-k3d-takserver/takserver-*:5.7-RELEASE-14` tags are published. Until then the package workflow skips. After they exist, confirm `uds run create-dev-package` clones the public chart and pulls those images, and that Zarf substitutes `TAK_IMAGE_TAG`.
- Fill `postgres-configuration`. The rendered `pg_hba.conf` and `postgres.conf` are empty.
- Publish the six TAK images, then run `uds run test-install` through to the gateway checks. The test bundle selects `istio-passthrough-gateway`. Upgrade stays skipped until a package tag exists. A 2 vCPU, 8 GB runner may still be too small for slim-dev; set `TEST_RUNNER` if it is.
- Decide how ATAK should reach 8089. Passthrough is SNI on gateway port 443, not a listener on 8089.
- Decide whether ports 8444, 9000, and 9001 need gateway hosts.
- SSO: browser login on the tenant gateway uses TAK's OIDC client against Keycloak. Ports 8443 and 8089 stay on client certificates. Authservice is not used.
- Mount `uds-trust-bundle` if TAK should trust the UDS CA. The chart has no value for that ConfigMap.
- Scheduling. The overlay uses 1Gi for config and 1536Mi for the API and messaging where the upstream developer example uses 8Gi, and it runs NATS as a single replica with clustering off. Postgres, Ignite, and NATS storage sizes have not been scheduled.
## License

This repository is `GPL-3.0-only`. TAK Server, which the images are built from, is GPL-3.0. SPDX headers use copyright `uds-k3d-takserver authors`. `uds run lint:all` checks those headers.

Private keys are not in the working tree. Commits earlier on this branch still have the old `chart/files/certs` files. Publishing a public copy needs a history that does not contain them.
