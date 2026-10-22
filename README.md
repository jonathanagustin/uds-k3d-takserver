# uds-k3d-takserver

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15775/badge)](https://www.bestpractices.dev/projects/15775)

https://github.com/user-attachments/assets/0b6ab8bf-ef9c-4a09-b52c-e3cb360ddc5d

[TAK Server](https://github.com/TAK-Product-Center/Server), the open-source Team Awareness Kit server, packaged as a [UDS](https://docs.defenseunicorns.com/core/) package. The package deploys the upstream TAK Server Helm chart (tag `5.7-RELEASE-14`) onto UDS Core. It is developed and tested on a local k3d cluster running the `k3d-core-slim-dev` bundle. The repository also has OpenTofu scaffolds for EKS, RKE2, and AKS test clusters.

> **Status:** pre-1.0 and under active development. See [Known limitations](#known-limitations).

## Features

- **Upstream chart, not a fork.** Zarf clones the public TAK Server chart when the package is created. A small config chart in `chart/` adds the UDS `Package` and the ConfigMaps that the upstream chart mounts.
- **Single sign-on with Keycloak.** The UDS operator registers a Keycloak client. TAK's own OpenID Connect client handles browser sign-in through one OpenID discovery entry. Keycloak groups map to TAK roles and groups. See [docs/sso.md](docs/sso.md).
- **Certificates generated at deploy time.** A pre-install Job runs TAK's `generateClusterCerts.sh`. No keys or keystores are committed. See [ADR 2](adr/0002-generate-certificates-at-deploy-time.md).
- **UDS networking.** The browser UI goes through the tenant gateway. Certificate-authenticated API, enrollment, and streaming traffic goes through the Istio passthrough gateway. NetworkPolicies are default-deny. See [docs/networking.md](docs/networking.md).
- **Clustered TAK Server.** The API, messaging, config, and plugins processes run alongside Ignite, NATS, and PostgreSQL in the `takserver` namespace.
- **Browser map with CloudTAK.** The optional `cloudtak` component runs [CloudTAK](https://github.com/dfpc-coe/CloudTAK) at `map.<domain>` with UDS Keycloak sign-in and connects it to TAK in the cluster. Each Keycloak user gets their own TAK certificate. It is built from a pinned submodule. CloudTAK is not WebTAK, which is not in the public TAK source. See [docs/cloudtak.md](docs/cloudtak.md).
- **Images built from source.** The TAK images are built from the public upstream source with Docker Buildx and published to GHCR under this repository. See [docs/building.md](docs/building.md).
- **Supply-chain checks.** CI runs Grype image scans, generates SBOMs, runs CodeQL, dependency review, and OpenSSF Scorecard, and supports optional keyless Cosign signing.

## Prerequisites

- Docker with enough resources for a local cluster. The [UDS local demo requirements](https://docs.defenseunicorns.com/core/getting-started/local-demo/basic-requirements/) call for at least 4 CPU, 10 GiB RAM, and 40 GiB disk. Podman can build images (`CONTAINER_RUNTIME=podman`), but only Docker is tested.
- [k3d](https://k3d.io/)
- [UDS CLI](https://docs.defenseunicorns.com/cli/getting-started/installation/), which includes Zarf:

  ```bash
  brew tap defenseunicorns/tap && brew install uds
  ```

All tools except Docker are pinned in [`mise.toml`](mise.toml). To install them, run:

```bash
mise install
```

## Supported architectures

| Architecture | Images | Zarf package | Tested in CI |
| --- | --- | --- | --- |
| `amd64` (x86_64) | yes | yes | install, and upgrade once a release exists |
| `arm64` (aarch64) | yes | yes | install |

The six TAK images are multi-arch: one tag such as `takserver-api:5.7-RELEASE-14` serves both, and Docker or the cluster pulls the matching one. Zarf packages are per architecture. `uds run create-dev-package` builds for the machine you run it on. To build or deploy for the other one, pass `--architecture`:

```bash
uds zarf package create . --flavor upstream --architecture arm64 --confirm
uds zarf package deploy zarf-package-takserver-arm64-*.tar.zst --confirm
```

A published release has an entry for each architecture under the same OCI reference. Pass `--architecture` to `zarf package deploy oci://...` or `uds deploy` when the cluster's architecture differs from the machine you deploy from. See [ADR 10](adr/0010-amd64-and-arm64.md).

The optional ATAK test device (`atak/`) is amd64 only and needs KVM on the node. Its Android VM image is Android-x86 under KubeVirt, and the APK is built for `x86_64` only. It is not part of the default package and is not built for arm64. The device has no GPS and reports a fixed test location in Washington, DC under the callsign `ATAK-DEVICE (TEST LOCATION)`. See [docs/atak-device.md](docs/atak-device.md).

## Quick start

Clone with the TAK Server source submodule. `build.sh` also checks it out if you forgot:

```bash
git clone --recurse-submodules --shallow-submodules https://github.com/jonathanagustin/uds-k3d-takserver
```

```bash
# 1. Build the six TAK images from the public source in upstream/takserver.
#    Set PUSH_IMAGES=true to push them to GHCR.
uds run build-image

# 2. Create the package, deploy k3d-core-slim-dev, deploy the test bundle,
#    create a Keycloak test user, and run the validation suite.
uds run test-install
```

Then open `https://takserver.uds.dev/` and sign in through Keycloak.

Other tasks (run `uds run --list` for the full list):

| Task | What it does |
| --- | --- |
| `uds run create-dev-package` | Create the Zarf package without an SBOM |
| `uds run dev` | Create the package and bundle, then deploy onto an existing cluster |
| `uds run default` | Same as `test-install` |
| `uds run test-upgrade` | Install the latest published package, then upgrade to the current branch |
| `uds run publish-package` | Create the package with its SBOM, test it, and publish it |
| `uds run lint:all` | Shared YAML, shell, Zarf, Helm, and license-header checks |
| `uds run cleanup` | Delete the k3d cluster and local package tarballs |

`hk check` runs the pre-commit checks defined in [`hk.pkl`](hk.pkl). To enable them as a git hook, run `hk install` once after `mise install`.

## Access

| Use | Host | Gateway | Service port |
| --- | --- | --- | --- |
| Browser UI (Keycloak SSO) | `takserver.<domain>` | tenant, 443, re-encrypted to TAK | 8447 (TLS) |
| Admin UI with a client certificate | `takserver-api.<domain>` | passthrough, SNI | 8443 |
| Streaming (ATAK / WinTAK) | `takserver-stream.<domain>` | passthrough, SNI | 8089 |
| Certificate enrollment | `takserver.<domain>` | passthrough, SNI | 8446 |
| CloudTAK map (Keycloak sign-in) | `map.<domain>` | tenant, 443 | 5000 in namespace `cloudtak` |

`<domain>` defaults to `uds.dev`. Ports 8443 and 8089 require a client certificate. The passthrough gateway does not terminate TLS, so the client presents its certificate directly to TAK Server.

**Browser sign-in:** members of the Keycloak group `/UDS Core/Admin` get `ROLE_ADMIN`. Groups under `/TAK/` with a `_READ` or `_WRITE` suffix become TAK groups. For example, `/TAK/Operators_READ` becomes the TAK group `Operators`.

**TAK clients:** the deploy-time Job writes the CA and an admin certificate to the ConfigMap `cert-migration`. Import the CA into the client trust store. Then either use the admin certificate or enroll a user certificate on port 8446 with a bearer token from the browser session. On k3d, host port 443 is the tenant gateway, so passthrough hosts need a port-forward to `passthrough-ingressgateway` or a load balancer in front of it. See [docs/sso.md](docs/sso.md) and [docs/networking.md](docs/networking.md).

## Architecture

```text
browser
  -> tenant gateway (HTTPS 443, takserver.<domain>)
    -> Service/takserver-web:8447 (TLS, verified against the TAK CA)

TAK client
  -> Istio passthrough gateway (SNI)
    -> Service/takserver-api-service:8446, :8443
    -> Service/takserver-messaging-service:8089
      -> Service/takserver-postgresql:5432
      -> Service/takserver-ignite
      -> Service/takserver-nats:4222

UDS operator
  -> Keycloak client uds-takserver (Secret takserver-sso)
  -> NetworkPolicy and Istio resources from the Package
```

Zarf installs the config chart (`chart/`) before the upstream chart. The config chart creates the `core-config` and `tak-ignite-config` ConfigMaps and the `reg-cred` Secret, and runs the pre-install Job that generates certificates and publishes the Ignite extensions jar. The upstream chart then deploys TAK Server. The `takserver-oidc` Pepr module adds an init container to the config, messaging, API, and plugins pods when each pod is created. That container substitutes the OIDC client secret into `CoreConfig.xml` before TAK Server starts.

Design decisions are recorded in [`adr/`](adr/):

1. [Record architecture decisions](adr/0001-record-architecture-decisions.md)
2. [Generate certificates at deploy time](adr/0002-generate-certificates-at-deploy-time.md)
3. [Do not add a Package monitor](adr/0003-no-prometheus-monitor.md)
4. [TAK OAuth uses one OpenID discovery entry on port 8447](adr/0004-tak-oauth-uses-openid-discovery.md)
5. [Stay inside what slim UDS Core and the stock chart provide](adr/0005-slim-core-boundaries.md)
6. [Re-encrypt tenant gateway traffic to the TAK web UI](adr/0006-re-encrypt-gateway-traffic-to-tak.md)
7. [Per-workload network rules inside the namespace](adr/0007-per-workload-network-rules.md)

## Documentation

| Doc | Covers |
| --- | --- |
| [Configuration](docs/configuration.md) | Zarf variables, the values overlay, resource sizing, and what the config chart mounts |
| [Single sign-on](docs/sso.md) | Keycloak client, group mapping, and certificate enrollment |
| [Networking](docs/networking.md) | Gateway exposure and the NetworkPolicy allow list |
| [Policy exemptions](docs/justifications.md) | Every UDS policy exemption and why it exists |
| [Data](docs/data.md) | PostgreSQL and what a backup of the namespace must include |
| [Building the images](docs/building.md) | Image build script, platforms, pins, and the Gradle cache |
| [CloudTAK](docs/cloudtak.md) | The browser map client: image, sign-in, TAK connection, rules, and limits |
| [ATAK test device](docs/atak-device.md) | Optional ATAK-CIV client in a KubeVirt VM, amd64 with KVM only |

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOMAIN` | `uds.dev` | Domain suffix for gateway hosts |
| `TAK_IMAGE_TAG` | `5.7-RELEASE-14` | Tag of the TAK images under `ghcr.io/jonathanagustin/uds-k3d-takserver` |

`values/common-values.yaml` is the overlay for the upstream chart. `values/test-values.yaml` is applied only by the test bundle and sizes TAK Server for a 2 vCPU, 8 GB node. See [docs/configuration.md](docs/configuration.md) for details on each value.

## Testing

`uds run test-install` runs the full suite against a fresh `k3d-core-slim-dev` cluster. The checks are defined in [`tasks/test.yaml`](tasks/test.yaml) and [`tests/`](tests/):

- Pod health, Istio mesh, UDS policy, and gateway checks
- `tests/api-smoke.sh` exercises the Marti API on ports 8443, 8447, 8446, and 8089
- `tests/oidc-render.sh` checks that every TAK pod rendered the OIDC client secret
- Playwright tests sign in through Keycloak, check the admin role and mapped groups, enroll a client certificate on 8446, and open the admin UI with a client certificate
- `test:cloudtak` and `tests/cloudtak.spec.ts` check the CloudTAK pods and rules, go from `map.<domain>` to the Keycloak login and back to the map as the Keycloak user, and require a live TAK connection with that user's certificate

In GitHub Actions, `.github/workflows/test.yaml` runs the install and upgrade paths on k3d. The EKS, RKE2, and AKS workflows (`test-eks.yaml`, `test-rke2.yaml`, `test-aks.yaml`) are manual and disabled by default. They use the OpenTofu scaffolds in `.github/test-infra/` and need cloud credentials.

## Repository layout

| Path | Purpose |
| --- | --- |
| `zarf.yaml` | Package metadata, variables, and image list |
| `common/zarf.yaml` | Config chart plus the upstream chart (tag `5.7-RELEASE-14`) |
| `chart/` | Config chart: UDS `Package`, ConfigMaps, and the certificate Job |
| `cloudtak/chart/` | CloudTAK chart: Deployment, PostGIS, and its UDS `Package` |
| `upstream/cloudtak` | CloudTAK source, a git submodule pinned to a release tag |
| `values/` | Values overlays for the upstream chart and the Pepr module |
| `pepr/` | `takserver-oidc` Pepr module that adds the OIDC render init container at admission |
| `bundle/` | Test bundle (passthrough gateway plus this package) and its config |
| `tasks.yaml`, `tasks/` | `uds run` tasks, built on [uds-common](https://github.com/defenseunicorns/uds-common) |
| `tests/` | API smoke script and Playwright tests |
| `docs/`, `adr/` | Documentation and architecture decision records |
| `.github/` | CI workflows, the image Dockerfile, and test infrastructure |

The layout follows the [UDS package guide](https://docs.defenseunicorns.com/core/how-to-guides/packaging-applications/create-uds-package/) and the [uds-packages/reference-package](https://github.com/uds-packages/reference-package).

## Known limitations

- The six TAK images are not published to GHCR yet, so build them before creating the package. `uds run test-upgrade` needs a published package release, and none exists yet.
- The upstream chart renders the `postgres-configuration` ConfigMap with empty `pg_hba.conf` and `postgres.conf` keys.
- External ATAK port 8089 is not mapped. Streaming is SNI on gateway port 443.
- Ports 8444, 9000, and 9001 are not exposed through a gateway.
- The upstream chart does not mount the `uds-trust-bundle` ConfigMap.
- CloudTAK's Keycloak sign-in is a route this package adds next to CloudTAK, because CloudTAK 13.111.3 has no OIDC route of its own. CloudTAK logout does not end the Keycloak session. CloudTAK's default basemap is OpenStreetMap through a tile proxy in its pod, with egress to that one host; set `basemap.enabled: false` where the cluster has no route to it. CloudTAK has no S3-backed features in this package. See [docs/cloudtak.md](docs/cloudtak.md).
- Resource requests are sized for a small development node, and NATS runs as a single replica with clustering off. Production sizing and storage are not tuned yet.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report bugs, request features, and send pull requests, including the coding standards and the test policy. Pull request titles follow [Conventional Commits](https://www.conventionalcommits.org/), and [release-please](https://github.com/googleapis/release-please) uses them to open release pull requests. Renovate keeps dependencies current. Its config extends the public `uds-common` preset.

## Security

Report vulnerabilities through a private GitHub security advisory. See [SECURITY.md](SECURITY.md).

## License

[GPL-3.0-only](LICENSE). TAK Server, which the images are built from, is also licensed under GPL-3.0. CloudTAK, which the optional `cloudtak` image is built from, is licensed under AGPL-3.0.
