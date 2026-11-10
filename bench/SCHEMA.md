# Benchmark record

Each run writes one JSON object per config and architecture. The file is
`bench/out/<arch>/<config>.json` and is uploaded as a workflow artifact.
Nothing under `bench/out/` is a source file. A record that could not measure
a field stores `null` and an entry in `errors`. It does not store zero.

`schema` is `1`.

| Field | Unit | How it is collected |
| --- | --- | --- |
| `arch` | `amd64` or `arm64` | `uname -m` on the runner |
| `config` | name | `bench/configs/<name>.yaml` |
| `git_sha` | git sha | `GITHUB_SHA` when it is set, otherwise `git rev-parse HEAD` |
| `recorded_at` | UTC timestamp | clock when the record is written |
| `footprint.cpu_requests_m` | millicores | sum of container CPU requests in `takserver` and `cloudtak` |
| `footprint.memory_requests_bytes` | bytes | sum of memory requests |
| `footprint.cpu_limits_m` | millicores or null | sum of CPU limits, null when any container has none |
| `footprint.memory_limits_bytes` | bytes or null | sum of memory limits, null when any container has none |
| `kubelet.peak_rss_bytes` | bytes | max working set from the kubelet Summary API during the load |
| `kubelet.steady_rss_bytes` | bytes | working set of the last sample |
| `kubelet.peak_cpu_nanocores` | nanocores | max of the kubelet's recent CPU average |
| `kubelet.steady_cpu_nanocores` | nanocores | last sample |
| `images.sum_bytes` | bytes | sum of layer sizes for this runner's platform, from `crane manifest` or `uds zarf tools registry manifest`, for every image in `zarf.yaml` |
| `images.unique_bytes` | bytes | same layers counted once, by digest |
| `package_bytes` | bytes | `stat` of the `zarf-package-takserver-*.tar.zst` just built |
| `start_phases.<app>.image_pull_s` | seconds | Sum over the pod's containers of kubelet `Pulling` to the next `Pulled` for the same container (`involvedObject.fieldPath`). Null when every image was already present, so there was no `Pulling` |
| `start_phases.<app>.inits` | list | each init container's `name` and `seconds` from its state timestamps |
| `start_phases.<app>.container_to_log_s` | seconds | main container `startedAt` to the first timestamped `Started TAK Server` or `Tomcat started on port` log line; includes entrypoint work, not JVM start/class-loading time |
| `start_phases.<app>.jvm_to_log_s` | seconds | Deprecated: null in new records because JVM start is not observed. Historical records used container start and must not be interpreted as JVM duration |
| `start_phases.<app>.evidence` | object | Pod UID/name, selected container ID/name/restart count, source container/init/Ready timestamps and pull event IDs/timestamps; startup marker name and timestamp only, no log contents. `jvm_started_at` stays null |
| `start_phases.<app>.log_to_ready_s` | seconds | that log line to the Ready condition; an observed interval, not isolated probe overhead |
| `time_to_ready.cold_s` | seconds | Ready condition minus pod creation, for the install's pods. Null when a pod has restarted |
| `time_to_ready.warm_s` | seconds | rollout restart of the TAK Deployments until Ready. Null for the baseline, which keeps the cold pods |
| `startup.max_generation` | count | highest `metadata.generation` on the TAK Deployments. 1 is a single rollout |
| `startup.max_restart_count` | count | highest container or init restart count on the four TAK apps |
| `load.clients` | count | the client count this record ran |
| `load.duration_s` | seconds | requested overall tester window, including client startup at one-second offsets |
| `load.counter_source` | string | `parent-cumulative-ramp-inclusive` for the bounded parent snapshot; absent in historical records |
| `load.messages_sent` | count | sum of every per-uid `messages_sent` the tester printed |
| `load.messages_received` | count | same, for `messages_received` |
| `load.connects` | count | same, for `connect_event_count` |
| `load.disconnects` | count | same, for `disconnect_event_count` |
| `load.pong_count` | count | same, for `pong_count` |
| `load.ping_pong_ms_sum` | milliseconds | same, for `time_between_ping_pong` |
| `load.ping_pong_ms_mean` | milliseconds | `ping_pong_ms_sum / pong_count`, null when `pong_count` is 0 |
| `load.p95_ms` | always null | this tester build stores a sum, not a latency histogram, so a p95 is not available |
| `ci.wall_clock_s` | seconds | filled by the summary job from the GitHub Actions job timestamps. Null in the per-arch file |
| `postgres` | object or null | TAK database `cot` over the load window. Null when `psql` could not be run, with the reason in `errors` |
| `postgres.hit_ratio` | 0 to 1, or null | `blks_hit / (blks_hit + blks_read)` from `pg_stat_database`. Null when both counters are 0 |
| `postgres.temp_files`, `postgres.temp_bytes` | count, bytes | `pg_stat_database` for `cot` |
| `postgres.checkpoints_timed`, `postgres.checkpoints_req` | count | `num_timed` and `num_requested` from `pg_stat_checkpointer` (PostgreSQL 17 and later) |
| `postgres.checkpoint_write_ms`, `postgres.checkpoint_sync_ms` | milliseconds | `write_time` and `sync_time` from `pg_stat_checkpointer` |
| `postgres.buffers_backend` | operations | legacy field name for the sum of `writes` in `pg_stat_io` for `client backend`; write operations, not blocks or bytes |
| `postgres.peak_rss_bytes`, `postgres.steady_rss_bytes` | bytes | working set of container `postgresql` in pod `takserver-postgresql-*`, from the same kubelet Summary samples as `kubelet` |
| `postgres.settings` | text | `current_setting` for `shared_buffers`, `work_mem`, `effective_cache_size`, `max_wal_size`, `checkpoint_timeout` |
| `errors` | strings | why a null field was not measured |

### Per-container capacity evidence

`capacity` is an additive schema-1 object. Older records have no such field.
It holds `sample_interval_s: 5`, `containers`, and collection `errors`. Each
container is identified by namespace, pod UID and container name, so a
replacement pod remains a separate row. It stores:

- `before` and `after`: Pod inventories around the sampling/load window,
  with the memory limit in bytes, restart count, readiness, current termination
  reason, last termination reason and pod phase. Succeeded pods are excluded;
  failed pods remain visible so their termination evidence is not lost.
  A missing boundary inventory is `null`.
- `samples`: peak and last `workingSetBytes`, peak and last `usageNanoCores`,
  memory/CPU observation counts, and first/last memory source timestamps from
  the kubelet Summary API. Missing metrics stay `null`; observed zero stays zero.

The collector retains aggregates for at most 256 container identities per
inventory and sampled set, rather than storing every poll. Truncation and
missing limits, status or samples are recorded as errors. The existing aggregate
footprint and Postgres fields are unchanged.

These are sampled working sets, not a continuous maximum or process RSS.
Before raising a load from 50 to 200 clients, inspect messaging's sampled peak
against its unchanged limit on both architectures, confirm adequate headroom,
and check that the pod identity, limit, restart count and healthy state persisted
across the window. An OOM termination, replacement, missing observation or sparse
sampling prevents a capacity conclusion. No automatic safe-capacity verdict is
made, and an absence of sampled pressure cannot guarantee no transient peak.

Throughput in the Pareto report is `messages_received / duration_s`. The
latency axis is `ping_pong_ms_mean`, not a p95. Footprint is
`kubelet.steady_rss_bytes`. The readiness plot uses only warm rollout duration.
Cold install age is copied into each config as a shared reference; it is shown
in the evidence table and never ranks swept configs. Dominance is decided only
among records with the same `git_sha`,
`load.clients`, `load.duration_s`, and architecture. Architectures share a scale
inside each matched cohort. Missing cohort metadata isolates a record. Missing
or invalid axes are not plotted; the markdown labels negative startup timings
invalid while preserving their original JSON values.

`<app>` is `takserver-messaging` or `takserver-api`. Run 39556568533 restarted messaging in 2m12s and the API in 1m52s on amd64. The probes poll every 10s. A startup log marker does not establish that the service meets readiness requirements; probe duration and scheduling also affect the interval. Isolated probe overhead remains unmeasured. `periodSeconds` stays 10. A class-data-sharing archive was not added: the class-loading share of that time is not in this record yet, and the archive would add bytes to both images for each arch. Container-to-log duration alone cannot justify that archive: exact JVM start and class-loading time remain unmeasured.

Run 39556568533 measured the old scale-down on validate-install. amd64 job 119079081806 spent 103s in Helm and then 5m21s restarting config, messaging, api, and plugins. arm64 job 119079081713 spent 98s in Helm and then 5m08s. `startup.max_generation` and `startup.max_restart_count` are how a later run shows that second rollout is gone. This file does not store that later run.

A config dominates another on one view when it is better or equal on both
axes of that view and strictly better on one. The three views are footprint
against throughput, footprint against mean latency, and footprint against warm
rollout duration. arm64 and amd64 are
separate series on one scale per cohort and view, so a
circle can be compared across architectures. Dominance is still decided
inside one architecture. Dominated configs are marked in the job summary and
drawn as open circles in the SVG.

Counters are cleared with `pg_stat_reset()` in `cot`, plus
`pg_stat_reset_shared('bgwriter')`, `pg_stat_reset_shared('checkpointer')` and
`pg_stat_reset_shared('io')`, just before the load. A reset failure is retained
in `errors`; the subsequent counter snapshot then has no verified load window.
Database hit/temp counters describe `cot`; checkpoint and I/O counters are
cluster-wide and can include background or other-database activity. On
PostgreSQL 18, [`pg_stat_io.writes`](https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-IO-VIEW)
counts write operations, while `write_bytes` is a separate, uncollected field.
The historical JSON key `buffers_backend` is retained without converting it
to blocks or bytes. The report shows the collected timed/requested checkpoints,
write/sync times, backend write operations, cache/temp counters and both working
set samples alongside throughput, mean latency and all five observed settings.

A config may set `postgres:` with those five parameters. The harness runs
`ALTER SYSTEM` inside `takserver-postgresql-0` and restarts the StatefulSet.
The next config in the same process resets them first, so a sweep does not
stack. The package does not copy a winning set into values: no load report
has put one on the front. `postgis-buffers` and `postgis-wal` are the two
tuned points. Both keep `shared_buffers` at or below 128MB, inside the 512Mi
limit. `effective_cache_size` is a planner hint and is not allocated. The
sweep does not set `fsync=off`.

Client certs are built at run time from `tests/extract-certs.sh` and are not
written into the repository or the image. The nightly workflow runs client
count 10. `bench/configs/*.yaml` lists 10, 50, and 200; set the workflow
input `clients` to `10,50,200` to run the full list. A config with `skip: true`
is not run. `gc-serial` is skipped because the image already passes
`UseG1GC` on the java command, after `JDK_JAVA_OPTIONS`, and a second
collector makes the JVM exit. CloudWatch export stays off. `--send-metrics`
is omitted because the tester's `type=bool` treats any present value as true.
`--skip-mission-api` is set because a run without a config file leaves
`mission_api_config` unset, and `tak_tester.py` 5.7-RELEASE-14 exits before
any client starts. `--send-metrics-interval` is one third of the duration, in
seconds, so a line is printed before the process is stopped. The printer
zeroes each counter after the line, so the record adds every line. Python is
started with `-u` so that line is not left in a block buffer.

### Counter window and provenance

The benchmark-bound tester suppresses the upstream per-client printers, which
otherwise print and reset each shared array at staggered intervals. At shutdown,
the parent emits each observed cumulative array once, before terminating children.
The parser retains the upstream counter names and sums those snapshots. A
connection count is observed connection events, not the requested clients or a
concurrent-connection gauge. No connection is inferred from a client being started.

The 60-second window includes the one-second-per-client startup ramp. A requested
50-client point therefore does not mean 50 clients sustained for 60 seconds.
Memory samples include the ramp and shutdown boundary. Arrays are locked one at
a time with a shared two-second snapshot budget, so this is not one atomic
cross-client instant; no counters from the later termination/join period are
intentionally included. A lock timeout invalidates the counters. Historical
interval-printer records omit unprinted tails and are not counter-equivalent.

## Optional exact JVM-start snapshot

Manual Benchmark dispatches can select `jvm_start_metadata=true` to enable the
existing observer with fixed context `k3d-uds`. It defaults off; PR, scheduled
and unselected runs make no new observer reads. Collection precedes load and
warmup, with no observer polling during measurement. It does not change the
50-client, five-minute warmup, twenty-minute measurement, three-repeat baseline.
The added pre-warmup work is not evidence of zero overhead or independent
cold/warm startup, class-loading duration or tuning benefit.

`BENCH_JVM_START_METADATA=1 BENCH_JVM_CONTEXT=k3d-uds` adds read-only JVM metadata
to the existing phase collector. Its explicit context must match kubectl's
current context, because the rest of the benchmark uses that context. Defaults
make no new reads and keep unobserved JVM timing null. The same bounded observer
is usable independently as `python3 -m bench.jvm_metrics --context k3d-uds
--app takserver-api` (or `takserver-messaging`). It does not create clusters,
restart workloads, alter probes/policies, attach to a JVM or install an agent.

The existing Java agent exports four numeric metrics: official
RuntimeMXBean-backed `process_start_time_seconds` and current/total/unloaded
class counts. Only these values survive parsing; other metric names, labels,
comments, complete payloads and command stderr are not returned. Duplicate
singleton series, unexpected labels, missing/nonfinite/nonintegral counts,
counter regression and malformed data are unavailable. The current-loaded
gauge may decrease normally. Epoch seconds preserve the received decimal;
derived epoch milliseconds round floating exposition to the MXBean resolution.

One exact Pod and named app container are required; a sidecar's position in the
Pod spec is irrelevant. Two immediate exact-Pod API-proxy reads are bracketed
by Pod identity reads. Pod UID, container ID, exact image-reference hash/image
digest, restart count and running-start timestamp must stay unchanged, as must
the official JVM start value. Only the fixed Pod proxy path on port 9100 is
used; denied/unsupported transport stays unavailable, with no remote endpoint
or port-forward fallback. Each app has a 15-second total command/cleanup budget,
a 2-second API request timeout, at most 2.9 seconds per command, a complete
64 KiB metrics stream cap and 1 MiB Pod JSON cap. Nonblocking stdout reads bound
memory; child process groups are killed/reaped without restricting legitimate
kubectl/UDS cache-file writes. Errors use fixed reason codes only.

`jvm_observation` retains this identity, both actual Unix/monotonic sample
brackets, the numeric samples, collector source SHA-256 and curated caller
source/run fields when present. Caller fields are supplied context, not an
independent attestation of checkout ownership or run success. Image references
are represented by their digest and exact-reference hash, not arbitrary URLs.
The same identity must match the phase's marker/init/Ready evidence before
`jvm_started_at` and `jvm_to_log_s` are filled. Changed/ambiguous identities and
negative/reordered timing leave them null. Historical records remain unchanged.

This is an existing-incarnation snapshot. JVM start is retrospective, but class
counts are from the actual scrape times after startup, not from the earlier
startup marker or Ready transition. No class evolution or loading-duration
claim follows, and no accumulated processing time is collected. A snapshot
of an existing Ready Pod is not a new cold/warm experiment or a capacity pass.
Both native-image metric/transport capability, genuine fresh/new cold/warm
incarnations, clock/overhead checks and repeated measurements remain empirical
gates for issue #48. Missing metadata never changes application readiness or
authorizes reuse. No startup pilot or tuning is dispatched by this option.

## Opt-in sustained synthetic baseline

The manual Benchmark input `study=synthetic-baseline` selects baseline only,
50 clients, three repeats, and the `synthetic-baseline-v1` protocol. It forces
`profile=baseline` and `clients=50`; schedule/PR/default short sweeps stay
unchanged. It installs once on each native architecture, marks that disposable
local k3d cluster with the shared ephemeral guard, and verifies the same proof
before each repeat. No tuning configurations or image build jobs are added.

Expected budget is 100–120 minutes per architecture (200–240 aggregate runner
minutes): 75 steady workload minutes plus approximately 2.5 minutes of client ramp
and installation, initialization and collection.
The existing 180-minute job limit remains the hard outer ceiling. The first
invalid repeat stops that architecture; no automatic retry or 200-client point
is authorized. No baseline study has been dispatched by this implementation.

Each repeat starts one parent with the same live TLS clients throughout a
300-second steady warm-up and 1200-second measured interval. A separate ramp
first has a 120-second deadline for all 50 actual child processes to be alive
and all 50 observed connection balances to equal one. Only then does the parent
publish READY and the runner begin the full 300-second warm-up; reconnect or
disconnect changes across that warm-up invalidate the point. The same sessions
continue through measurement. After warm-up, the runner reads raw database
statistics and boundary inventory, then sends a local-file GO/START/END handshake. The pre-install bootstrap guard refuses an
already existing cluster/context; the marker cannot retroactively claim one. The parent
snapshots all shared counters and starts its measured clock; a second snapshot
ends the interval before client termination. Each snapshot has the existing
shared two-second array-lock budget and retains per-UID monotonic read timestamps
and snapshot begin/end timestamps. Capture is sequential across clients, not an
atomic cross-client sample. Elapsed time must be 1200–1203 seconds. The record
retains both snapshots and exact parent wall/monotonic boundaries. Only their
deltas contribute to measured rates/mean ping-pong latency. All 50 identities
must have one observed connection at both boundaries and no intervening
connect/disconnect events. The parent also checks the real CoT children's
liveness throughout startup/warm-up/measurement; intentionally exited printer
helpers are excluded. No requested-client concurrency is inferred.

The pinned XML CoT implementation counts self-SA and ping in messages sent;
missions are disabled, so their difference gives observed self-SA sends. Each
client must contribute at least 216 self-SA sends, 216 pings and 216 pongs
(90% of the 240 nominal five-second ticks), plus received broadcast progress.
This is an explicit workload/performance acceptance threshold, not a dead-client
inference or a corruption diagnosis. Fewer pongs/receives can be a real overload
observation. Such points retain their raw before/after counters, are classified
`workload-performance-failed`, stop further repeats and cannot support a tuning
front or a capacity-pass claim. A real child exit is classified separately.

`--interval 5` explicitly requests one self-SA update per five seconds per
client: 10 offered self-SA updates/s. Ping probes run every 5000 ms and offline
metrics printing is disabled. Sent/received message rates retain upstream
counter semantics, including protocol/control traffic and receiver fan-out;
received/offered is not a delivery percentage. There is no p95 estimate.

Raw PostgreSQL snapshots are retained as `postgres.window_before/window_after`;
existing counter fields contain their nonnegative deltas. Reset timestamps
from the database/checkpointer/I/O views must match across both snapshots. No shared database
statistics are reset in this mode. Actual settings must remain identical;
PostgreSQL 18/PostGIS 3.6 are checked. The database snapshot brackets must be
within five seconds of the parent counter boundaries. These are explicit small
brackets rather than a transactional atomic cross-system instant. A counter
reset, failed/missing boundary or excessive skew invalidates the record.

`study` retains source commit, tester/config SHA-256, repeat number, workload
settings, runner machine/kernel/logical CPU count, boundary timestamps, bounded
5-second per-container memory/CPU samples (maximum 400 batches/256 containers),
and fixed-path cgroup-v2 `memory.max`/`cpu.max` at both boundaries. The database
must retain its 512Mi cgroup limit. `capacity` retains configured limits, Pod UID,
container/image IDs and before/after restart/readiness/OOM evidence. Sampler
startup follows the parent's start handshake; stopping follows its end handshake
with 200 ms polling. The source timestamps remain available for inspecting the
boundary lag. Working set is not process RSS or a continuous maximum.

`baseline-r1/r2/r3.json` prevent overwrites. An invalid record remains available
and cannot enter the sustained-study front. Reporting isolates this protocol
from historical ramp-inclusive records, keeps individual repeats, and provides
median/range only when all three valid repeats are present. These repeats share
one cluster's data/cache history and are not independent cluster replications.
Native hosted-runner differences remain confounded with architecture. This is
an exploratory synthetic baseline, not production representativeness, a tuning
recommendation or an architecture ranking. Issues #49/#51 remain open. Choose
two justified tuning points only after the baseline identifies a bottleneck;
do not compare a named preset that merely reproduces actual default settings.
