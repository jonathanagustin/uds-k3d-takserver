# CI workflows

Every check in this repository runs as a GitHub Actions workflow in [`.github/workflows/`](../.github/workflows/). This page lists each workflow, what starts it, and what it checks. Times are in UTC.

Docs, device, benchmark, demo, unit-test-only, and repository metadata changes skip the install and upgrade matrices. Test and Package ignore the paths in [`.github/scripts/runtime-paths.sh`](../.github/scripts/runtime-paths.sh). A chart, Pepr module, network policy, value, bundle, task, image build, dependency pin, or script those jobs run still starts them. A chart SVG is one of those files. The Docs workflow builds the docs site. Full Core decides in its own `changes` job.

## Pull request checks

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Lint | `lint.yaml` | every pull request, and pushes to `main` | Runs `hk check` (the checks in [`hk.pkl`](../hk.pkl)) and the shared uds-common lint workflow |
| PR Title Check | `commitlint.yaml` | every pull request | Checks that the title follows Conventional Commits, with the shared uds-common commitlint workflow |
| Test | `test.yaml` | pull requests and pushes to `main` that change a relevant path ([`runtime-paths.sh`](../.github/scripts/runtime-paths.sh)) | Builds the CloudTAK and PostGIS images when their inputs changed, waits for the six TAK images, then runs the install test and the upgrade test from the last release, each on amd64 and arm64. On pushes to `main`, and on pull requests with the `upgrade-pg15` label, it also runs the upgrade from release 0.6.0 (PostgreSQL 15) on both architectures. `verify-test` reports the result. A superseded run skips `verify-test` instead of failing it |
| Unit tests | `unit-tests.yaml` | every pull request, and pushes to `main` | Pepr module tests and the Python upgrade helper tests, with coverage in the job summary. Also the Loki query helper, CoreConfig cache listener, profile, benchmark harness, and Full Core summary tests, and the package values render. See [Coverage](../CONTRIBUTING.md#coverage) |
| Package | `package.yaml` | the same relevant paths as Test, pushes of those paths to `main`, and by hand | Waits for the images, then creates the dev package on amd64 and arm64, checks its architecture, and publishes it as `ghcr.io/jonathanagustin/uds-k3d-takserver/ci-packages/takserver:<arch>-<key>`. See [Package reuse](#package-reuse) |
| Scan | `scan.yaml` | pull requests that change the package, charts, values, bundle, image builds, or submodules | Compares image scans with `uds-pk scan compare` and posts the result as a pull request comment |
| CodeQL | `codeql.yaml` | every pull request, pushes to `main`, and Mondays at 06:00 | CodeQL code scanning |
| Dependency Review | `dependency-review.yaml` | every pull request | GitHub dependency review of the changed dependencies |
| Docs | `docs.yaml` | changes to `docs-site/`, `docs/`, `adr/`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, or `CHANGELOG.md` | Builds the docs site. A broken internal link fails the build. On `main` it also deploys the site to GitHub Pages |

A pull request whose files are all on that ignore list skips Test and Package. One relevant file still runs them, on amd64 and arm64. Full Core decides in its own `changes` job and skips the deploy when the diff does not need it. The checks that `main` requires still report on every pull request: `hk`, both CodeQL `Analyze` jobs, and `dependency-review`. Those workflows have no path filter. Lint, unit tests, and the PR title check run on every pull request too.

Stricter review on `main` (one human approval, admins included, an up-to-date branch) is written in [Review rules for main](branch-protection.md). Those settings are not on.

## Package reuse

The dev package is created once per architecture and set of inputs. `.github/scripts/dev-package.sh key` hashes the working tree after `pin-image-tags.sh` (so the image tags count) of every tracked file that can reach the package, plus the UDS CLI version, the create variables and the architecture. The Package workflow publishes it under that key; the tag is written once and never overwritten. Test, Full Core and Benchmark deploy the slim checkpoint first, then `create-dev-package` pulls the published package, waiting up to 10 to 15 minutes for the Package workflow (stopping once that run finishes without the tag), and creates it locally only when no package appears. Fork pull requests cannot publish, so they create in-job as before. `DEV_PACKAGE_REUSE=false` or `KEY_SALT` forces a create.

The upgrade test deploys only the `takserver` package on the upgrade step when the branch's `core-base` bundle entry (ref and overrides) is the same as the released one; otherwise it redeploys Core too.

## Images

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Container | `container.yaml` | changes to `.github/container-and-chart/`, the TAK submodule, or the workflow, and by hand | Builds the six TAK images on native amd64 and arm64 runners when their inputs changed, scans them, writes software bills of materials (SBOMs), and joins the two architectures into one index. See [Building the images](building.md) |
| CloudTAK image | `cloudtak-image.yaml` | changes to the CloudTAK submodule or its build, and by hand | Builds the CloudTAK image per architecture and writes the multi-arch index. See [CloudTAK](cloudtak.md#image) |
| PostGIS image | `postgis-image.yaml` | changes to the PostGIS build, and by hand | Builds the PostGIS image per architecture and writes the multi-arch index. See [ADR 13](../adr/0013-build-the-postgis-image-here.md) |
| Cosign | `cosign.yaml` | by hand only, with the `sign` input | Signs the published TAK images with keyless Cosign |

The image workflows also attest the images they push. See [Verify a release](../README.md#verify-a-release).

## ATAK test device

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| ATAK | `atak.yaml` | changes to the APK build or the `upstream/atak-civ` submodule, and by hand | Builds the ATAK-CIV APK and uploads it |
| ATAK device VM | `atak-vm.yaml` | changes to `atak/vm/`, `atak/ci/`, or `atak/viewer/`, and by hand | Builds the containerDisk and the viewer, boots Android under KubeVirt on k3d, reaches it over adb, and opens the phone view in a browser |
| ATAK e2e | `atak-e2e.yaml` | changes to `atak/`, pushes to `main` that change `atak/`, and by hand | Deploys UDS Core slim and TAK Server, then the device, and checks that it connects. The device images come from GitHub Container Registry (GHCR) when their inputs are unchanged. A push to `main` moves the `5.5.1.10` tags to the tested images. See [Reused build outputs](#reused-build-outputs) and [ATAK test device](atak-device.md) |

### Reused build outputs

The ATAK e2e run reuses anything whose inputs have not changed, so a typical run spends its time on the test, not on builds.

- **Device images.** [`atak/ci/device-images.sh`](../atak/ci/device-images.sh) tags each image with the ATAK version and a short hash of the files it is built from (including the script itself, which holds the build commands), for example `atak-civ-vm:5.5.1.10-e73f1e6f97ba`. When that tag is in GHCR, the run pulls it. The images are `atak-civ-apk` (the APK alone), `atak-driver`, `atak-civ-vm`, and `atak-viewer`. The `images` job builds and pushes only the missing ones, at the same time as the e2e job deploys UDS Core and TAK Server. Fork pull requests cannot push, so their e2e job builds the images itself before the deploy.
- **APK build cache.** [`atak/ci/build-apk.sh`](../atak/ci/build-apk.sh) writes each Dockerfile stage to `build-cache:atak-apk-<stage>-<hash>`. A stage whose tag exists is skipped, and a tag is never rewritten.
- **ATAK Zarf package.** After a passing run, the job publishes the package to `packages/atak-device:5.5.1.10-<hash>`. The next run with the same package inputs and images deploys it from GHCR instead of creating it.
- **UDS Core slim checkpoint.** [`deploy-slim-core.sh`](../.github/scripts/deploy-slim-core.sh) pulls `k3d-core-slim-dev` from this repository's mirror (`checkpoints/k3d-core-slim-dev`) and checks its digest. The `mirror-checkpoint.yaml` workflow copies new versions from upstream. When the mirror lacks a version, the script pulls from upstream (`ghcr.io/defenseunicorns/dev/uds/checkpoints`). ATAK e2e also keeps the 5.5 GB tarball in the Actions cache. Only `main` and manual runs save it.

A Renovate bump of `slim_core_version` runs the mirror workflow on its pull request. The workflow copies the new version and prints the digest line to add to `slim_core_digests`. Until that line is added, the script pulls the new version by tag and warns.

To force a rebuild of every keyed image, change `KEY_SALT` in `device-images.sh`.

## Scheduled and opt-in gates

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Full Core | `full-core.yaml` | daily at 07:17, by hand, pull requests labeled `full-core`, and pull requests or pushes to `main` that change backup, monitoring, UDS Core integration, the bundles, or Full Core's own workflow and tests (`.github/scripts/full-core-paths.sh`) | The `full-core` job reports success when the run passed or was not needed, so it can be a required check. A cancelled validation skips that job instead of failing it. Deploys full UDS Core and the package on amd64 and arm64, then runs `test:all` and `test:full-core`. See [ADR 15](../adr/0015-full-core-is-a-scheduled-gate.md) |
| Benchmark | `benchmark.yaml` | daily at 09:41, by hand, and pull requests labeled `benchmark` | Installs the current branch, runs the TAK load tester, and plots the results. See [Benchmarks](benchmarks.md) |
| Scorecard | `scorecard.yaml` | Saturdays at 01:30, pushes to `main`, branch protection changes, and by hand | OpenSSF Scorecard, through the shared uds-common workflow |
| Mirror the UDS Core checkpoint | `mirror-checkpoint.yaml` | changes to the checkpoint versions, and by hand | Copies each `k3d-core-slim-dev` version that CI deploys into this repository's GHCR, with the same digest |
| Demo Video | `demo.yaml` | pull requests that change the demo scripts, and by hand | Records the demo videos. Only a manual run from `main` publishes and signs them. See [Demo videos](../CONTRIBUTING.md#demo-videos) |

A pull request without the `benchmark` label skips Benchmark. Full Core also runs without its label when the path filter matches. Adding the label, or pushing to a pull request that already has it, runs the job.

## Concurrency

Test, Package, Benchmark, the image workflows, and the ATAK workflows each use one concurrency group per workflow and ref. A newer pull request push cancels only that pull request's older run. A newer push to `main` cancels only that workflow's older push. Two pull requests do not cancel each other, and a pull request does not cancel `main`.

A schedule and a `workflow_dispatch` each get a group of their own, so they are not cancelled and they do not wait behind a push. Release keeps `cancel-in-progress: false` and groups by tag. Demo Video is unchanged. A finished run is kept.

On `main`, the previous setting left the running validation in place (`cancel-in-progress` false) and queued the newest push behind it. One pending run was allowed, so an older hung run held every later push until the job timeout. Cancelling the superseded push drops that run. The nightly Full Core and a manual benchmark stay in their own groups, so a push does not cancel them.

Full Core puts that group on `validate-full-core`, per architecture, and only when the path check said to run. A docs push still reports the `full-core` check, and it does not cancel a validation that is already in progress. `verify-test` and `full-core` skip themselves when the run was cancelled, so the cancelled run does not leave a failed aggregate on the new head.

## Releases

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Release Please | `release-please.yaml` | pushes to `main` | Opens or updates the release pull request. When a release is created, it calls the Release workflow |
| Release | `release.yaml` | a published release, a call from Release Please, and by hand with an existing tag | Builds the released package with its SBOM on amd64 and arm64, signs it keylessly, publishes it, and attests its build provenance. See [Verify a release](../README.md#verify-a-release) |

## Other clusters

The EKS Test, RKE2 Test, and AKS Test workflows (`test-eks.yaml`, `test-rke2.yaml`, `test-aks.yaml`) run only by hand, and only when the `enabled` input is set. Each one sets up OpenTofu and validates its scaffold in [`.github/test-infra/`](../.github/test-infra/). Per their inputs, they create nothing and only initialize OpenTofu.

## Runner setup

The cluster jobs run on the standard 4 CPU GitHub runners, so a few scripts make room before the deploy:

- `.github/scripts/trim-runner.sh` deletes preinstalled toolchains and Docker images the tests never use. The install job once ran out of disk inside the k3d node without it.
- `.github/scripts/add-runner-swap.sh` grows the runner's swap to 8G for Full Core. The full UDS Core layers plus TAK need more memory than the runner keeps free. Outside CI it changes nothing.
- `.github/scripts/deploy-slim-core.sh` turns off k3s datastore compaction (`etcd-compaction-interval=0`) on CI clusters. A compaction that ran past its 5 second timeout made k3s exit mid-deploy about every other run. A local cluster keeps the default.
- `uds run fit-runner` (`.github/scripts/fit-runner.sh`) scales down slim checkpoint pods the TAK tests do not need. That frees CPU for the `core-base` upgrade.

After a failed test, `.github/scripts/dump-memory.sh` prints runner memory and node allocatable. It also prints any out-of-memory (OOM) kills, k3d node restarts, `kubectl top`, and each container's last state. The step has a 5 minute timeout so a dead API server cannot hang the job.

## Logs when an upload hangs

`actions/upload-artifact` has hung past its step timeout in the install, upgrade and Full Core jobs. Before the uploads, `.github/scripts/print-logs.sh` prints the last 300 lines of each log the job uploads (at most 60 files) in collapsed groups, so the job log keeps them. Upload steps time out after 5 minutes, and the job timeout stops a hang the step timeout misses.
