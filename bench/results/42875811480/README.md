<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# 50-client synthetic baseline: three repeats per native runner

[Run 42875811480](https://github.com/jonathanagustin/uds-takserver/actions/runs/42875811480), source [`ceb901e139688b2258de1362a105ac5a569e94a9`](https://github.com/jonathanagustin/uds-takserver/commit/ceb901e139688b2258de1362a105ac5a569e94a9), completed successfully on amd64 and arm64. All six records pass the collector's workload, boundary and stability checks. This is one baseline configuration on one disposable cluster per architecture, with three successive fresh client sessions sharing application/data/cache history. It is not a configuration sweep, independent cluster replication, architecture ranking or production capacity result.

The protocol held 50 observed client identities through at least 300 seconds of steady warmup and a 1200-second measured window. Each client contributed at least 237 self-SA sends, pings and pongs during measurement (acceptance minimum 216), with zero measured reconnect/disconnect deltas. Actual warmups were 302.059–302.190 s; measured windows 1200.104–1200.658 s. Config templates list 10/50/200 options, but this study forced 50; no 200-client point ran.

Original records are under [records/](records/). [sources.json](sources.json) retains run/source/job/artifact identities, verified ZIP digests and every original file hash. [Generated tables](report.md) use the existing source-hash-recorded reporter. Raw bytes were preserved, not rewritten or normalized.

## Observed repeated baseline

Values are median [minimum–maximum] across the three records on each runner, not confidence intervals or ISA effects.

| Native runner | Valid repeats | Received messages/s | Mean ping-pong ms | Last sampled application working set MiB | Sampled peak application working set MiB |
| --- | --- | --- | --- | --- | --- |
| amd64 | 3/3 | 494.792 [494.721–494.822] | 385.229 [374.255–399.803] | 3962.715 [3950.566–4006.395] | 3968.973 [3964.004–4006.758] |
| arm64 | 3/3 | 495.294 [495.269–495.630] | 452.877 [430.011–470.297] | 3912.352 [3911.762–3967.723] | 3948.566 [3929.945–3988.238] |

Offered self-SA was 10 updates/s; observed self-SA was 9.896–9.910/s. Sent messages include ping/control traffic; received messages include fan-out. Neither received/offered nor received/sent is a delivery percentage. The latency is the counter-weighted mean of observed ping-pong samples, not p95; p95 remains unavailable. Both jobs observed four logical CPUs and the same kernel release, but host hardware/contention differences remain confounded with architecture.

## Resources and PostgreSQL

Every poll includes all 13 inventoried TAK/CloudTAK containers. Before/after Pod, container and image identities, restart counts, readiness and configured memory limits agree; no recorded OOM or collection error occurred. Sampled per-container maxima remained below declared limits. These application namespaces exclude UDS Core, node services and the runner-side load tester: the aggregate is not total host consumption or proof of host capacity.

There were 224–230 polls per repeat, but only 63–84 distinct kubelet memory timestamps per container. Cached first readings can precede the measured start by 20.58 s; final readings can lag the endpoint by 24.16 s. Host observation timestamps are inside the measured window, but source metrics are cached. Label peaks as sampled maxima and the final value as last observed working set, not continuous maxima, exact endpoint values or a strict five-second source cadence. No cpu.stat/throttling evidence was collected.

PostgreSQL 18.6/PostGIS 3.6.4 and settings were unchanged: shared_buffers=128MB, work_mem=4MB, effective_cache_size=4GB, max_wal_size=1GB, checkpoint_timeout=5min. Both cgroup boundaries retain 512 MiB and 0.5 CPU for PostgreSQL; other memory limits come from Pod specifications. All six windows have four timed and zero requested checkpoints, zero temp files/bytes and measured cache-hit ratio 1.0. These are window deltas, not lifetime counters. Checkpoint write/sync values are reported window-summed milliseconds, not request latency or CPU utilization.

| Native runner | Checkpoint write ms range | Checkpoint sync ms range | Backend write operations range | Sampled PostgreSQL peak working set MiB range |
| --- | --- | --- | --- | --- |
| amd64 | 217520–364468 | 18–68 | 11891–11905 | 88.160–138.477 |
| arm64 | 239555–365037 | 23–37 | 11918–11923 | 79.113–135.484 |

No database settings were tuned. This baseline does not satisfy the default-versus-two-tuned-settings experiment or justify a preset that simply reproduces current defaults.

## JVM startup metadata is partial

Nine of 12 application/repeat joins are available: API on both architectures and messaging on amd64, with exact Pod/container/image/restart identities, official RuntimeMXBean epoch start and two bounded metric reads. The collector source hash matches the recorded run source. API JVM-to-startup-log time is 73.832 s on amd64 and 52.047 s on arm64; amd64 messaging is 58.507 s. Those values repeat because each architecture reused the same application incarnations, not because three independent starts were measured.

ARM messaging is unavailable in all three records: `marker_after_ready`. Its startup marker is `18:42:51.059396Z`, while the retained whole-second Ready time is `18:42:51Z`. The existing conservative guard rejects that 59 ms ordering; no JVM duration or transport success is inferred from discarded observations, and missing values remain null. No guard was relaxed.

The shared cold-install reference of 170 s (amd64) / 131 s (arm64) occurs once per architecture and is repeated in records; warm rollout time is null. Class counts are later scrape-time observations, not startup class-loading duration/share. The metadata option ran before load; there is no overhead comparison. These snapshots do not justify CDS, probe changes or startup tuning.

## What remains open

- #48: genuine independent cold/warm incarnations and complete messaging/API metadata on both architectures; class-loading and overhead evidence; a measured benefit/cost tradeoff before any tuning.
- #49: representative default-versus-two-justified-tuned-settings experiment, preserving memory, durability and upgrade/backup constraints. This report supplies a repeated synthetic default baseline only.
- #51: matched results for at least three configurations and an evidence-backed ADR. Three successive baseline repeats are not three configurations or an ISA ranking.

No default, badge, production recommendation or 200-client capacity claim changes with this evidence.
