# CI workflows

Every check in this repository runs as a GitHub Actions workflow in [`.github/workflows/`](../.github/workflows/). This page lists each workflow, what starts it, and what it checks. Times are in UTC.

Docs, device, benchmark, demo, unit-test-only, and repository metadata changes skip the install and upgrade matrices. Test and Package ignore the paths in [`.github/scripts/runtime-paths.sh`](../.github/scripts/runtime-paths.sh). A chart, Pepr module, network policy, value, bundle, task, image build, dependency pin, or script those jobs run still starts them. A chart SVG is one of those files. So is [`mise.toml`](../mise.toml): it pins Node, k3d, Helm, the UDS CLI, and pnpm in the same file as the linters, and a change to any of those pins starts Test and Package. The Docs workflow builds the docs site. Full Core decides in its own `changes` job.

## Pull request checks

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Lint | `lint.yaml` | every pull request, and pushes to `main` | Runs `hk check` (the checks in [`hk.pkl`](../hk.pkl)) and the shared uds-common lint workflow |
| PR Title Check | `commitlint.yaml` | every pull request | Checks that the title follows Conventional Commits, with the shared uds-common commitlint workflow |
| Test | `test.yaml` | pull requests and pushes to `main` that change a relevant path ([`runtime-paths.sh`](../.github/scripts/runtime-paths.sh)) | Builds the CloudTAK and PostGIS images when their inputs changed, waits for the six TAK images, then runs the install test and the upgrade test from the last release, each on amd64 and arm64. On pushes to `main`, and on pull requests with the `upgrade-pg15` label, it also runs the upgrade from release 0.6.0 (PostgreSQL 15) on both architectures. `verify-test` reports the result. A superseded run skips `verify-test` instead of failing it |
| Unit tests | `unit-tests.yaml` | every pull request, and pushes to `main` | Pepr module tests and the Python upgrade helper tests, with coverage in the job summary. Also the Loki query helper, CoreConfig cache listener, profile, benchmark harness, and Full Core summary tests, and the package values render. See [Coverage](../CONTRIBUTING.md#coverage) |
| Package | `package.yaml` | the same relevant paths as Test, pushes of those paths to `main`, and by hand | Waits for the images, then creates the dev package on amd64 and arm64, checks its architecture, and publishes it as `ghcr.io/jonathanagustin/uds-takserver/ci-packages/takserver:<arch>-<key>`. See [Package reuse](#package-reuse) |
| Scan | `scan.yaml` | pull requests that change the package, charts, values, bundle, image builds, or submodules | Compares image scans with `uds-pk scan compare` and posts the result as a pull request comment |
| CodeQL | `codeql.yaml` | every pull request, pushes to `main`, and Mondays at 06:00 | CodeQL code scanning |
| Dependency Review | `dependency-review.yaml` | every pull request | GitHub dependency review of the changed dependencies |
| Docs | `docs.yaml` | changes to `docs-site/`, `docs/`, `adr/`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, or `CHANGELOG.md` | Builds the docs site and runs its browser tests. A broken internal link fails the build. On `main` it also deploys the site to GitHub Pages |

A pull request whose files are all on that ignore list skips Test and Package. One relevant file still runs them, on amd64 and arm64. Full Core decides in its own `changes` job and skips the deploy when the diff does not need it. The checks that `main` requires still report on every pull request: `hk`, both CodeQL `Analyze` jobs, and `dependency-review`. Those workflows have no path filter. Lint, unit tests, and the PR title check run on every pull request too.

[Review rules for main](branch-protection.md) describes the solo-maintainer policy and the optional independent-review policy. The proposed administrator-bypass and up-to-date-branch changes have not been applied. Required approvals on `main` remain at zero while the repository has one collaborator.

## Airgap install check

Test includes an amd64 airgap install variant. It prepares the package and
bundle, blocks external egress inside the k3d nodes, then deploys the applications
and runs the core tests. The runner keeps its network access. Cleanup attempts to restore
the node firewall rules; check its result before reusing the test cluster. See [Airgap test boundaries](justifications.md).

The HTTP control checks direct network reachability before and after blocking.
A passing control does not establish that the application suite passed. Full
airgap validation is still in progress; see [issue #256](https://github.com/jonathanagustin/uds-takserver/issues/256).

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
| ATAK uptime native | `atak-uptime-native.yaml` | changes to the viewer freshness check or that workflow, and by hand | Runs the freshness check against Prometheus 3.16.0 on a standard runner. A fresh success passes. A success still inside the lookback, and a broken status, fail. It does not deploy the device |

Manual **ATAK e2e** runs accept an `uptime_probe` boolean. It adds only the Core
monitoring layer, leaves Grafana at zero replicas, and checks the authenticated
`/phone.html` target in Prometheus after the device test. The option is off by
default while its extra memory and CPU footprint is measured beside the VM, so
a pull request run does not exercise it.
`tests/test_atak_uptime.py` is a stand-in for the query API, not a Prometheus
server. It also renders kube-prometheus-stack 92.14.0, the chart in Core
monitoring 1.16.0, and checks that `kubeStateMetrics.enabled: false` omits
the kube-state-metrics Deployment while Prometheus remains. ATAK uptime native runs the same check against Prometheus and records
a fresh success, a success still inside the lookback, and a broken status.
That job does not deploy Core monitoring, Blackbox, or the ATAK device, so it
does not prove the authenticated `/phone.html` probe.
See [Check the viewer uptime probe](atak-device.md#check-the-viewer-uptime-probe).

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
| Benchmark | `benchmark.yaml` | Mondays at 09:41, by hand, and pull requests labeled `benchmark` | Installs the current branch, runs the TAK load tester, and plots the results. Adding a different label does not start it and does not cancel a run already going. See [Benchmarks](benchmarks.md) |
| Scorecard | `scorecard.yaml` | Saturdays at 01:30, pushes to `main`, branch protection changes, and by hand | OpenSSF Scorecard, through the shared uds-common workflow |
| Mirror the UDS Core checkpoint | `mirror-checkpoint.yaml` | changes to the checkpoint versions, and by hand | Copies each `k3d-core-slim-dev` version that CI deploys into this repository's GHCR, with the same digest |
| Demo Video | `demo.yaml` | pull requests that change the demo scripts, and by hand | Records the demo videos. Only a manual run from `main` publishes and signs them. See [Demo videos](../CONTRIBUTING.md#demo-videos) |

A pull request without the `benchmark` label skips Benchmark. Adding that label, or pushing to a pull request that already has it, runs the job. Adding any other label does not. Full Core also runs without its label when the path filter matches. Adding the `full-core` label, or pushing to a pull request that already has it, runs that job. A push to `main` still runs Full Core when the pushed commits change a Full Core path.

## Concurrency

Test, Package, Benchmark, the image workflows, and the ATAK workflows each use one concurrency group per workflow and ref. A newer pull request push cancels only that pull request's older run. A newer push to `main` cancels only that workflow's older push. Two pull requests do not cancel each other, and a pull request does not cancel `main`.

A schedule and a `workflow_dispatch` each get a group of their own, so they are not cancelled and they do not wait behind a push. Benchmark's weekly run uses that same isolation. A pull request label other than `benchmark` also gets its own run id, so it does not cancel a benchmark validation. Release keeps `cancel-in-progress: false` and groups by tag. Demo Video is unchanged. A finished run is kept.

On `main`, the previous setting left the running validation in place (`cancel-in-progress` false) and queued the newest push behind it. One pending run was allowed, so an older hung run held every later push until the job timeout. Cancelling the superseded push drops that run. The nightly Full Core and a manual benchmark stay in their own groups, so a push does not cancel them.

Full Core puts that group on `validate-full-core`, per architecture, and only when the path check said to run. A docs push still reports the `full-core` check, and it does not cancel a validation that is already in progress. `verify-test` and `full-core` skip themselves when the run was cancelled, so the cancelled run does not leave a failed aggregate on the new head.

## Releases

| Workflow | File | Runs on | What it does |
| --- | --- | --- | --- |
| Release Please | `release-please.yaml` | pushes to `main` | Opens or updates the release pull request. When a release is created, it calls the Release workflow, then rebuilds Docs after successful package publication and provenance |
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

### Hosted-runner routing stalls

After a failed install, upgrade, or Full Core deploy,
`.github/scripts/runner-wedge-probe.sh` checks `ip -4 route` before Docker,
Kubernetes, and Falco diagnostics. Routing has a five-second budget and a
one-second kill grace; the kernel-log probe has a ten-second budget and the
same grace. If routing times out, those network diagnostics are skipped.
Local log sanitizing and printing still run. A missing command or permission
is reported as inconclusive and does not suppress diagnostics.
If the probe does not return within 20 seconds, the step still exits 0 and
records the route as stalled only if the routing probe has not reported yet.
A healthy route stays healthy when only the kernel-log probe hangs. Probe output
is spooled locally so blocked descendants cannot retain the step log pipes.
The wrapper signals the probe process group without waiting for stuck tasks.
That timeout is not the install or upgrade
failure; the failed deploy step above it is.

This identifies the runner failure investigated in [issue #300](https://github.com/jonathanagustin/uds-takserver/issues/300).
It does not repair the kernel, interrupt a process stuck in uninterruptible
kernel sleep, or guarantee that the runner can finish reporting to GitHub.
The deploy keeps its original failure result. Rerun the failed job once on a
fresh runner and retain the image and kernel notice for the investigation.

The cluster jobs temporarily compare `ubuntu-22.04` on AMD64 and
`ubuntu-22.04-arm` on native ARM64 for [#300](https://github.com/jonathanagustin/uds-takserver/issues/300)
and [#103](https://github.com/jonathanagustin/uds-takserver/issues/103).
Test, Full Core and Benchmark retain the AMD64 `TEST_RUNNER` override;
image builds and other workflow runners keep their existing labels.
The metadata-only [AMD64 comparison](https://github.com/jonathanagustin/uds-takserver/actions/runs/42528864369)
observed kernel `6.8.0-1070-azure` on Ubuntu 22 and `7.0.0-1017-azure`
on Ubuntu 24; the [ARM64 probe](https://github.com/jonathanagustin/uds-takserver/actions/runs/42529079902)
also observed `7.0.0-1017-azure` on Ubuntu 24. This is a temporary label
comparison, not a kernel root-cause finding or proof of a universal fix.
Ubuntu 22 is deprecated and [retires on 2027-04-17](https://github.com/actions/runner-images/issues/14254),
so retain this comparison only while the supported-runner investigation continues.
Cluster workflows select Python 3.12 explicitly before deployment and test virtual
environments. The pinned QUIC dependencies require a newer interpreter than the
Ubuntu 22 system Python 3.10; their package versions and assertions stay pinned.

Lint, Unit tests, CodeQL, dependency review, image scanning, and PR title checks
cancel superseded runs for the same pull request or branch. CodeQL schedules
remain separate from push validation. Test, Lint, Unit tests,
and PR title checks do not rerun when a milestone is assigned. PR title checks
still validate title and body edits, so a skipped edit cannot replace a failed
required title check.

## Limits on supporting jobs

Build, index, scan, and reporting jobs have explicit job timeouts rather than
GitHub's six-hour default. Fast aggregate checks stop within five minutes;
manifest/index jobs within fifteen; lint within twenty; CodeQL and docs builds
within thirty; image scan comparison within sixty. OpenTofu scaffold validation
and Release Please stop within fifteen minutes. Existing cluster, image-build,
and release-publishing limits are unchanged. A timeout remains a failed check;
these limits do not suppress errors or automatically retry failed work.

The shared lint workflow receives only its automatic GitHub token. Container
image jobs keep package publication and attestation permissions, but Actions API
access is read-only. Scorecard uses a local reusable adapter that accepts only
the optional `SCORECARD_READ_TOKEN`. Its upstream call inherits that restricted context, rather
than all repository secrets. The pinned analysis still supplies SARIF artifacts,
code-scanning uploads and badge publication. The adapter retains the upstream
permission contract; it does not change the token fallback when the named secret
is unset. Neither reusable layer attaches an environment with additional secrets.

## Image producer queues

Test and the dedicated CloudTAK/PostGIS workflows resolve the same immutable
input tags before scheduling native architecture builds. Their build jobs share
one concurrency group per image key and architecture; index writers have a
separate group per image key. A queued job rechecks the published input label
before compiling. PostGIS smoke checks and attestations remain inside the build
job; publication and index validation retain their existing failure behavior.
Manual force rebuilds still rebuild explicitly, under the same queue.

These jobs use GitHub's [`queue: max` concurrency policy](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency),
with cancellation disabled inside the shared group. Unlike the default single
pending slot, this preserves up to 100 FIFO waiters; GitHub cancels overflow
rather than growing an unlimited queue. A failed producer releases its slot,
and the next producer can build the missing tag. Existing workflow/job limits
still bound execution; package/index consumers retain their bounded waits.
Different input keys and architectures do not share a global pending queue.
Fork token permissions and fallback behavior are unchanged.

Local tests validate the workflow queue contracts and run the real PostGIS build
script against a registry fixture to check reuse after serialization and retry
after a failed producer. Existing hosted runs also verify serialized publication,
post-admission reuse and failed-producer takeover; [issue #353](https://github.com/jonathanagustin/uds-takserver/issues/353)
records that evidence. This does not quantify minute savings or promise that
failed compilation is never repeated. No cold builds were dispatched solely to
demonstrate savings.

## Documentation after release publication

Release Please creates releases with `GITHUB_TOKEN`, which does not start the
separate `release: published` Docs trigger. It calls the existing Docs workflow
once after the Release workflow succeeds, with the published tag as an input.
The call checks out the current main renderer, fetches all tags, and verifies
that the published tag exists in main before building. The latest guides can
therefore advance without depending on the earlier, concurrent main-push build.

Main, direct release events and reusable calls share one workflow publication
group, so an older running build cannot deploy after a newer release build.
Pull request previews retain their separate ref groups and cancellation policy.
Docs errors surface in the Release Please workflow's `docs` job; they do not
silently count as a successful dispatch. Only that job requests Pages and OIDC
permissions for documentation; it cannot publish packages or modify releases.

## Released upgrade bootstrap compatibility

The upgrade test reads the exact verified release's `core-base` reference and
Pepr dependency and controller version as data. Both Pepr pins must match.
Known Core/Pepr pairs select a pinned checkpoint;
missing, duplicate or unknown metadata fails before deployment. Known releases
0.7, 0.10 and 0.11 use Core 1.16.0 and Pepr 2.0.7, so they bootstrap directly
on 1.16.0.
This removes only an unnecessary Core transition before the released app baseline.
It is not a kernel or runner-stall fix.

The pinned 0.6 PostgreSQL 15 test still starts on 1.15.0 to preload its required
Pepr 2.0.3 controller before its own Core 1.15.2 bundle. It retains the real older
Core and PostgreSQL 15-to-18 upgrade path. Checkpoint archive cleanup uses the
same selected version. The published package selection and upgrade assertions
remain unchanged.

The upgrade test also builds a local actions-only Zarf package as an admission
readiness barrier. It runs after checkpoint restoration and again between the
released Core and TAK packages in the same bundle deployment. Native Zarf waits
require the agent Deployment to be Available, a ready Endpoint address referencing
a Pod, and the HTTPS target port 8443. Their successive deadlines total at most
360 seconds; a failed wait stops deployment without restarting the agent or
weakening its webhook. Failure diagnostics use bounded requests and redact the
current and previous agent logs. This gate reports infrastructure readiness; it
does not establish the cause of a runner kernel failure.

The local barrier leaves the released signed package bytes and verification rules
unchanged. Keeping one baseline bundle deployment preserves package order and
cross-package imports and exports. Normal deployment runs the barrier even after
its standalone deployment; `--resume` is deliberately not used.

## Manual staged failure categories

Manual staged failures publish a small `failure-categories.json` alongside
progress. It contains only source/run identity, an allowlisted failed step,
fixed diagnostic pattern IDs and counts capped at 32. The publisher reads at
most the existing 64 KiB private command tail, refuses nonregular files,
symlinks, oversized files and invalid text, and classifies the entire retained
stream before selecting output. It never publishes private tail text, matching
strings, command arguments, URLs, environments or exception messages. Private
evidence remains excluded from artifact copying.

The command runner retained this tail **before** redaction; it may begin inside
a credential or omit the original error. It is therefore unsafe to publish even
a subsequently redacted excerpt. Categories are diagnostic signatures, not
causal proof: unrelated output can match a pattern, and `unclassified` means
no approved signature was present in the retained tail. Missing evidence or a
category cannot count as acceptance or authorize retries, rollback, bypasses or
changes to ownership. The structured progress journal remains authoritative
only for the stage and its recorded result.

The runner creates its first private failure capture exclusively with mode
0600. Existing files and symlinks are never followed or overwritten, so later
failed observations cannot replace that retained tail. This still does not
recover discarded output or establish a causal explanation for that failure.

### Optional encrypted private failure capture

The manual Staged migrations workflow accepts `diagnostic_recipient`, an optional
age X25519 **public** recipient (`age1…`). Its empty default downloads and installs
nothing. A successful trial also performs no encryption. Only after the selected
trial fails can the helper encrypt the fixed regular, non-symlink
`staged-migrations/owner/PRIVATE-command-failure.txt`, bounded to 64 KiB. It cannot
select another input file, take a private key or invoke an age plugin. The
existing fixed JSON categories and all acceptance requirements remain unchanged.

The helper requires this repository's manual main run and a matching checkout
SHA and failed owner-journal source/run/attempt identity. It verifies the official
age v1.3.2 release archive and extracted executable,
and checks executable integrity before and after encryption. HTTPS acquisition
preserves runner proxy/CA trust; the encryption child receives no inherited
credentials or loader flags. Execution is bounded to 15 seconds, ciphertext to
72 KiB and private stderr to 4 KiB. No captured stderr or exception text is
printed. Only successful encryption and postchecks mark the separate ciphertext
artifact ready; failed/partial output is removed. The uploaded path is exactly
`staged-encrypted-diagnostic/first-failure.age`, with seven-day retention.

Official [age v1.3.2](https://github.com/FiloSottile/age/releases/tag/v1.3.2) pins:

| Linux architecture | Archive SHA-256 | Executable SHA-256 |
| --- | --- | --- |
| amd64 | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` | `eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c` |
| arm64 | `6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4` | `41b072352f4561018949623c674d16ef704019b9108a9bbdbd21292efebfc94f` |

Generate and retain any identity with official `age-keygen` outside repositories,
with restrictive permissions. Supply only its public recipient to the workflow.
Keep decrypted evidence private as well: for example, use `umask 077` and redirect
`age --decrypt --identity /secure/identity.txt downloaded.age` to a private file,
never the terminal or an issue. Verify the artifact's run, attempt and source
through GitHub metadata before interpreting its contents. Encryption protects
confidentiality; it does not turn diagnostics into acceptance, recover discarded
tail bytes, establish a causal explanation or authorize another trial.
