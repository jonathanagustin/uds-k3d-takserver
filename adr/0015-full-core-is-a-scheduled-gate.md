# 15. Full UDS Core is a scheduled gate

Date: 2026-10-24

## Status

Accepted

## Context

Per-PR CI deploys `k3d-core-slim-dev` and the slim test bundle. That never installs the logging, monitoring, backup, runtime security, metrics-server, or Portal layers. Those layers do not fit beside TAK on a 2 vCPU node.

No workflow in this repository sets a larger GitHub-hosted runner label. amd64 jobs use `vars.TEST_RUNNER` when it is set, and `ubuntu-24.04` otherwise. arm64 jobs use `ubuntu-24.04-arm`. The Test workflow already trims preinstalled toolchains. It does not add swap. amd64 is pinned to `ubuntu-24.04` instead of `ubuntu-latest`: GitHub is moving `ubuntu-latest` to 26.04 between 2026-10-19 and 2026-11-19, and on 26.04 the Zarf checkpoint extraction under `/tmp` fails with `disk quota exceeded`.

`create:test-bundle` in uds-common looks for `uds-bundle.yaml` in the directory given as `path`. A file named `bundle/uds-bundle-full.yaml` would not be that input.

The slim checkpoint includes `uds-k3d-dev`, which installs MinIO in `uds-dev-stack`. Velero's default `VELERO_BUCKET_PROVIDER_URL` points at that MinIO. `fit-runner` scales the MinIO Deployment to 0 so the core-base upgrade can schedule. The checkpoint script's default version on main is still `1.15.0`. The bundles pin core-base at `1.15.2-upstream`.

## Decision

- Slim stays the per-PR gate ([ADR 0005](0005-slim-core-boundaries.md)). Full core runs in `.github/workflows/full-core.yaml`, on pushes to main, on a nightly schedule, on `workflow_dispatch`, and on pull requests labeled `full-core`. It is not a job in `test.yaml`, because a schedule on that workflow would rerun `validate-install`.
- The bundle is `bundle/full/uds-bundle.yaml`. It upgrades `core-base` the same way the slim bundle does, then deploys `core-metrics-server`, `core-logging`, `core-runtime-security`, `core-backup-restore`, `core-monitoring`, and `core-portal` at `1.15.2-upstream`, with the same keyless identity as `core-base`, then `takserver` with `cloudtak`.
- `uds run test-full-core` deploys the cached slim checkpoint with `SLIM_CORE_VERSION=1.15.2`, then the full bundle, then `test:all`, then `test:full-core`. The checkpoint script's default is unchanged.
- The job uses the same runner labels as `validate-install`, runs `trim-runner.sh`, and adds an 8G swapfile. It does not invent a runner label.
- `test:full-core` waits until every Deployment, StatefulSet, and DaemonSet in the layer namespaces is rolled out and its pods are Ready, prints those pods, and requires `kubectl top pods` in `takserver` and `cloudtak` to return numeric usage. That output is uploaded. The same memory requests and limits `tasks/test.yaml` asserts are compared with the live specs, and a pod whose top memory is over the sum of its container memory limits fails the job.
- Velero pod readiness is required. BackupStorageLocation availability is printed and is not required. MinIO may be scaled to 0.

## Consequences

- Whether every layer becomes Ready on a public GitHub runner is visible only after this workflow runs. Layer requests were not reduced to force a fit.
- Adding files under `bundle/` changes the Zarf cache key used by `validate-install` once, on the next cache miss. The full-core job restores that cache and does not save a second copy.
- `validate-install` is not on the nightly schedule, so its per-PR runtime is unchanged.
- A pull request without the `full-core` label skips the job. Adding the label, or pushing to a pull request that already has it, runs the job.
