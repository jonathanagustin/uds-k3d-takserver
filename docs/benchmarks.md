# Benchmarks

The Benchmark workflow measures how much processor time and memory TAK Server uses under a Team Awareness Kit (TAK) client load, and how long it takes to become ready, for several resource configs. The nightly run on `main` has completed on both architectures since November 2, 2026, for example [run 41613491855](https://github.com/jonathanagustin/uds-takserver/actions/runs/41613491855). Those runs use 10 clients for 60 seconds, once per config. Treat the front as a first look, not a sizing decision. The results are in the run's `bench-front` artifact and its job summary. This page describes the harness.

## When it runs

The [retained ten-client snapshot](../bench/results/42361079121/README.md)
contains matched baseline, Postgres buffers and Postgres write-ahead log (WAL) records from
November 7, 2026, on both architectures, with source hashes and a corrected
report. It records why those observations do not justify a tuning change,
architecture default, or a 200-client load.

[`.github/workflows/benchmark.yaml`](../.github/workflows/benchmark.yaml) runs:

- Mondays at 09:41 Coordinated Universal Time (UTC)
- by hand (`workflow_dispatch`)
- on a pull request labeled `benchmark`

It runs on amd64 and arm64 runners. The weekly run uses client count 10. To run more, set the workflow input `clients` to a comma-separated list such as `10,50,200`, or to `all` for every count a config lists.

Manual runs also accept `profile`: `all` (the default) keeps the full sweep;
`baseline` measures only the unchanged install, without tuning rollouts.
With `clients=10,50`, baseline produces two points per architecture instead of
fourteen across the seven enabled profiles. Installation and its tests still
run on both architectures. Scheduled and labeled runs keep the full sweep.
This option does not establish 50-client headroom or relax the gate on 200 clients.
The 60-second window includes clients starting one second apart. Requested
clients and observed connection events do not establish sustained concurrency.
New records identify their cumulative parent-snapshot counters; older interval
reports could omit late clients and final partial intervals. See the
[counter provenance](../bench/SCHEMA.md#counter-window-and-provenance) before
comparing results.

## What one run does

1. Installs the current branch with `uds run test-install`, with this commit's TAK, CloudTAK, and PostGIS images.
2. Fetches the upstream TAK load tester (`src/testing/load_test` from the same commit as the `upstream/takserver` submodule, `5.7-RELEASE-14`) and installs its pinned Python requirements from `bench/load-test-requirements.txt`.
3. Runs `bench/run.py`. For each config in `bench/configs/` that is not marked `skip: true`, and for each selected client count, it applies the config to the running cluster, runs the load, and writes `bench/out/<arch>/<config>.json`. A second or later client count adds `-c<count>` to the file name.
4. Uploads the records as the `bench-<arch>` artifact. If the install or the sweep fails, it also uploads the cluster debug output and logs as `debug-log-bench-<arch>-<run>-<attempt>`, with passwords masked by `.github/scripts/redact-logs.py`.
5. The `benchmark-summary` job runs `bench/report.py` on all the records it finds, so one failed architecture still leaves a front for the other. It fails when neither architecture uploaded a record. It writes `front.md` and `front.svg` and uploads them as the `bench-front` artifact. The report is also shown in the job summary.

Client certificates for the load are built at run time from `tests/extract-certs.sh`. They are not written into the repository or an image.

## Configs

Each file in [`bench/configs/`](../bench/configs/) changes memory settings, Java virtual machine (JVM) flags, or Postgres settings on the running cluster. Before the next config, `bench/run.py` puts the previous config's changes back. Each lists client counts 10, 50, and 200 and a 60-second load.

| Config | What it changes |
| --- | --- |
| `baseline` | Nothing. The test bundle's current requests, limits, and JVM flags. Its cold time-to-ready is the install itself, with no rollout restart |
| `heap-768` | Sets `JDK_JAVA_OPTIONS` to `-Xms768m -Xmx768m` on the application programming interface (API), messaging, and config containers |
| `postgis-memory` | Raises the CloudTAK PostGIS memory request to 512Mi and limit to 1Gi |
| `postgis-buffers` | TAK Postgres `shared_buffers` 128MB, `work_mem` 4MB, `effective_cache_size` 384MB, `max_wal_size` 256MB, `checkpoint_timeout` 5min, through `ALTER SYSTEM` and a restart |
| `postgis-wal` | A smaller cache and fewer checkpoints than `postgis-buffers`: `shared_buffers` 64MB, `effective_cache_size` 256MB, `max_wal_size` 128MB, `checkpoint_timeout` 15min |
| `small` | Memory requests and limits from the `small` [values profile](profiles.md) |
| `production` | Memory requests and limits from the `production` [values profile](profiles.md) |
| `gc-serial` | Uses the serial collector for garbage collection (GC) on the API, messaging, and config containers. Skipped: the image already passes `UseG1GC`, and a second collector makes the JVM exit |

The configs set memory, JVM flags, and Postgres settings only. Central processing unit (CPU) allocation stays at whatever the install set. Beside the load, each record holds the Postgres counters (`pg_stat_database`, `pg_stat_checkpointer`, `pg_stat_io`) and the `postgresql` container working set. The harness resets those counters before each config. Earlier runs, such as run 41613491855, did not reset the checkpoint counters or the `cot` database counters. In those runs the values add up from one config to the next.

## The record and the report

[`bench/SCHEMA.md`](../bench/SCHEMA.md) defines every field in a record and how it is collected. A field that could not be measured is `null`, with the reason in `errors`. It is never stored as zero.

The report compares configs on three views: footprint against throughput, footprint against mean latency, and footprint against warm rollout duration. The initial cold install age is copied into every config as a shared reference, so it stays in the evidence table and never ranks swept configs. Cold and warm readiness measurements do not compete. Each view is split into cohorts with the same source revision, client count and load duration. Records missing one of those fields are isolated, so an unknown workload cannot dominate another record. A config is on the Pareto front for a view when no other config in the same cohort and on the same architecture is at least as good on both axes and better on one. Dominated configs are drawn as open circles. Both architectures share one scale on each cohort's plot, but dominance is decided inside one architecture. See [architecture decision record (ADR) 19](../adr/0019-compare-arches-on-one-scale.md).

The markdown report includes the observed CPU, working set, throughput, latency, startup phases, Postgres counters and record caveats. Missing timings stay "not measured"; negative or non-finite timings are shown as invalid and never treated as durations. The source records are unchanged. A startup-phase row describes the pod present when that config was collected. A Postgres-only rollout can reuse an earlier TAK pod, so repeated rows are not independent cold and warm TAK startup measurements.

A setting is copied into the package only after a report puts it on the front. The nightly records are one 10-client run per config. Do not treat any config, or either [values profile](profiles.md), as a sizing result yet.

## Check capacity before a larger load

New records retain `capacity.containers` from the same five-second kubelet
polls as the aggregate working set. Each row has the namespace, pod UID and
container name, sampled memory/CPU peaks and last values, source timestamps,
and before/after memory limits, readiness, restart counts and termination
reasons. Older records do not have this evidence. See the
[record schema](../bench/SCHEMA.md#per-container-capacity-evidence).

For the 50-client point, inspect `takserver-messaging` on both architectures
before attempting 200 clients. Compare its sampled working-set peak with its
memory limit, require headroom, and check that its UID, limit, healthy state and
restart count stayed stable. Review both termination-reason fields for OOMs.
Do not infer messaging's headroom from the total TAK and CloudTAK working set.
Missing data, a changed pod or limit, restarts, or insufficient samples leave
the gate unresolved. Polling can miss a transient peak, so a small observed
margin is not evidence that a larger load fits.

The collector bounds its stored identities and retains aggregates, not a
time-series dump. It changes neither client-count defaults nor workload limits.
