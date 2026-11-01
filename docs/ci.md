# CI workflows

Every check in this repository runs as a GitHub Actions workflow in [`.github/workflows/`](../.github/workflows/). This page lists each workflow, what starts it, and what it checks. Times are in UTC.

Doc-only changes skip the cluster workflows. Test, Package, and Full Core ignore changes to Markdown files, images, `docs/`, `adr/`, and a few repository settings files. The Docs workflow builds the docs site instead.

## Pull request checks

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Lint | `lint.yaml` | every pull request, and pushes to `main` | Runs `hk check` (the checks in [`hk.pkl`](../hk.pkl)) and the shared uds-common lint workflow |
| PR Title Check | `commitlint.yaml` | every pull request | Checks that the title follows Conventional Commits, with the shared uds-common commitlint workflow |
| Test | `test.yaml` | pull requests that change more than docs, and pushes to `main` | Builds the CloudTAK and PostGIS images when their inputs changed, waits for the six TAK images, then runs the install test on amd64 and arm64 and the upgrade test from the last release. `verify-test` reports the result |
| Unit tests | `unit-tests.yaml` | every pull request, and pushes to `main` | Pepr module tests and the Python upgrade helper tests, with coverage in the job summary, plus the Loki query helper and CoreConfig cache listener tests. See [Coverage](../CONTRIBUTING.md#coverage) |
| Package | `package.yaml` | pull requests that change more than docs, and by hand | Waits for the images, then creates the dev package on amd64 and arm64 and checks its architecture |
| Scan | `scan.yaml` | pull requests that change the package, charts, values, bundle, image builds, or submodules | Compares image scans with `uds-pk scan compare` and posts the result as a pull request comment |
| CodeQL | `codeql.yaml` | every pull request, pushes to `main`, and Mondays at 06:00 | CodeQL code scanning |
| Dependency Review | `dependency-review.yaml` | every pull request | GitHub dependency review of the changed dependencies |
| Docs | `docs.yaml` | changes to `docs-site/`, `docs/`, `adr/`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, or `CHANGELOG.md` | Builds the docs site. A broken internal link fails the build. On `main` it also deploys the site to GitHub Pages |

## Images

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Container | `container.yaml` | changes to `.github/container-and-chart/`, the TAK submodule, or the workflow, and by hand | Builds the six TAK images on native amd64 and arm64 runners when their inputs changed, scans them, writes SBOMs, and joins the two architectures into one index. See [Building the images](building.md) |
| CloudTAK image | `cloudtak-image.yaml` | changes to the CloudTAK submodule or its build, and by hand | Builds the CloudTAK image per architecture and writes the multi-arch index. See [CloudTAK](cloudtak.md#image) |
| PostGIS image | `postgis-image.yaml` | changes to the PostGIS build, and by hand | Builds the PostGIS image per architecture and writes the multi-arch index. See [ADR 13](../adr/0013-build-the-postgis-image-here.md) |
| Cosign | `cosign.yaml` | by hand only, with the `sign` input | Signs the published TAK images with keyless Cosign |

The image workflows also attest the images they push. See [Verify a release](../README.md#verify-a-release).

## ATAK test device

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| ATAK | `atak.yaml` | changes to the APK build or the `upstream/atak-civ` submodule, and by hand | Builds the ATAK-CIV APK and uploads it |
| ATAK device VM | `atak-vm.yaml` | changes to `atak/vm/`, `atak/ci/`, or `atak/viewer/`, and by hand | Builds the containerDisk and the viewer, boots Android under KubeVirt on k3d, reaches it over adb, and opens the phone view in a browser |
| ATAK e2e | `atak-e2e.yaml` | changes to `atak/`, pushes to `main` that change `atak/`, and by hand | Deploys UDS Core slim and TAK Server, then the device, and checks that it connects. A push to `main` publishes the device images. See [ATAK test device](atak-device.md) |

## Scheduled and opt-in gates

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Full Core | `full-core.yaml` | daily at 07:17, pushes to `main`, by hand, and pull requests labeled `full-core` | Deploys full UDS Core and the package on amd64 and arm64, then runs `test:all` and `test:full-core`. See [ADR 15](../adr/0015-full-core-is-a-scheduled-gate.md) |
| Benchmark | `benchmark.yaml` | daily at 09:41, by hand, and pull requests labeled `benchmark` | Installs the current branch, runs the TAK load tester, and plots the results. See [Benchmarks](benchmarks.md) |
| Scorecard | `scorecard.yaml` | Saturdays at 01:30, pushes to `main`, branch protection changes, and by hand | OpenSSF Scorecard, through the shared uds-common workflow |
| Demo Video | `demo.yaml` | pull requests that change the demo scripts, and by hand | Records the demo videos. Only a manual run from `main` publishes and signs them. See [Demo videos](../CONTRIBUTING.md#demo-videos) |

A pull request without the `full-core` or `benchmark` label skips that job. Adding the label, or pushing to a pull request that already has it, runs the job.

## Releases

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Release Please | `release-please.yaml` | pushes to `main` | Opens or updates the release pull request. When a release is created, it calls the Release workflow |
| Release | `release.yaml` | a published release, a call from Release Please, and by hand with an existing tag | Builds the released package with its SBOM on amd64 and arm64, signs it keylessly, publishes it, and attests its build provenance. See [Verify a release](../README.md#verify-a-release) |

## Other clusters

The EKS Test, RKE2 Test, and AKS Test workflows (`test-eks.yaml`, `test-rke2.yaml`, `test-aks.yaml`) run only by hand, and only when the `enabled` input is set. Each one sets up OpenTofu and validates its scaffold in [`.github/test-infra/`](../.github/test-infra/). Per their inputs, they create nothing and only initialize OpenTofu.
