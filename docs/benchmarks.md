# Benchmarks

The Benchmark workflow measures how much CPU and memory TAK Server uses under a client load, and how long it takes to become ready, for several resource configs. The nightly run on `main` has completed on both architectures since November 2, 2026, for example [run 41613491855](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/41613491855). Those runs use 10 clients for 60 seconds, once per config. Treat the front as a first look, not a sizing decision. The results are in the run's `bench-front` artifact and its job summary. This page describes the harness.

## When it runs

[`.github/workflows/benchmark.yaml`](../.github/workflows/benchmark.yaml) runs:

- daily at 09:41 UTC
- by hand (`workflow_dispatch`)
- on a pull request labeled `benchmark`

It runs on amd64 and arm64 runners. The nightly run uses client count 10. To run more, set the workflow input `clients` to a comma-separated list such as `10,50,200`, or to `all` for every count a config lists.

## What one run does

1. Installs the current branch with `uds run test-install`, with this commit's TAK, CloudTAK, and PostGIS images.
2. Fetches the upstream TAK load tester (`src/testing/load_test` from the same commit as the `upstream/takserver` submodule, `5.7-RELEASE-14`) and installs its pinned Python requirements from `bench/load-test-requirements.txt`.
3. Runs `bench/run.py`. For each config in `bench/configs/` that is not marked `skip: true`, and for each selected client count, it applies the config to the running cluster, runs the load, and writes `bench/out/<arch>/<config>.json`. A second or later client count adds `-c<count>` to the file name.
4. Uploads the records as the `bench-<arch>` artifact.
5. If both architectures succeed, the `benchmark-summary` job runs `bench/report.py` on all records. It writes `front.md` and `front.svg` and uploads them as the `bench-front` artifact. The report is also shown in the job summary.

Client certificates for the load are built at run time from `tests/extract-certs.sh`. They are not written into the repository or an image.

## Configs

Each file in [`bench/configs/`](../bench/configs/) changes memory settings, JVM flags, or Postgres settings on the running cluster. Before the next config, `bench/run.py` puts the previous config's changes back. Each lists client counts 10, 50, and 200 and a 60-second load.

| Config | What it changes |
| --- | --- |
| `baseline` | Nothing. The test bundle's current requests, limits, and JVM flags. Its cold time-to-ready is the install itself, with no rollout restart |
| `heap-768` | Sets `JDK_JAVA_OPTIONS` to `-Xms768m -Xmx768m` on the API, messaging, and config containers |
| `postgis-memory` | Raises the CloudTAK PostGIS memory request to 512Mi and limit to 1Gi |
| `postgis-buffers` | TAK Postgres `shared_buffers` 128MB, `work_mem` 4MB, `effective_cache_size` 384MB, `max_wal_size` 256MB, `checkpoint_timeout` 5min, through `ALTER SYSTEM` and a restart |
| `postgis-wal` | A smaller cache and fewer checkpoints than `postgis-buffers`: `shared_buffers` 64MB, `effective_cache_size` 256MB, `max_wal_size` 128MB, `checkpoint_timeout` 15min |
| `small` | Memory requests and limits from the `small` [values profile](profiles.md) |
| `production` | Memory requests and limits from the `production` [values profile](profiles.md) |
| `gc-serial` | Serial garbage collector (GC) on the API, messaging, and config containers. Skipped: the image already passes `UseG1GC`, and a second collector makes the JVM exit |

The configs set memory, JVM flags, and Postgres settings only. CPU stays at whatever the install set. Beside the load, each record holds the Postgres counters (`pg_stat_database`, `pg_stat_checkpointer`, `pg_stat_io`) and the `postgresql` container working set. The harness resets those counters before each config. Earlier runs, such as run 41613491855, did not reset the checkpoint counters or the `cot` database counters. In those runs the values add up from one config to the next.

## The record and the report

[`bench/SCHEMA.md`](../bench/SCHEMA.md) defines every field in a record and how it is collected. A field that could not be measured is `null`, with the reason in `errors`. It is never stored as zero.

The report compares configs on three views: footprint against throughput, footprint against mean latency, and footprint against ready time. A config is on the Pareto front for a view when no other config on the same architecture is at least as good on both axes and better on one. Dominated configs are drawn as open circles. Both architectures share one scale on each plot, but dominance is decided inside one architecture. See [ADR 19](../adr/0019-compare-arches-on-one-scale.md).

A setting is copied into the package only after a report puts it on the front. The nightly records are one 10-client run per config. Do not treat any config, or either [values profile](profiles.md), as a sizing result yet.
