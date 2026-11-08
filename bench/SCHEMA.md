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
| `start_phases.<app>.jvm_to_log_s` | seconds | main container `startedAt` to the first `Started TAK Server` or `Tomcat started on port` log line |
| `start_phases.<app>.log_to_ready_s` | seconds | that log line to the Ready condition. This is the probe lag |
| `time_to_ready.cold_s` | seconds | Ready condition minus pod creation, for the install's pods. Null when a pod has restarted |
| `time_to_ready.warm_s` | seconds | rollout restart of the TAK Deployments until Ready. Null for the baseline, which keeps the cold pods |
| `startup.max_generation` | count | highest `metadata.generation` on the TAK Deployments. 1 is a single rollout |
| `startup.max_restart_count` | count | highest container or init restart count on the four TAK apps |
| `load.clients` | count | the client count this record ran |
| `load.duration_s` | seconds | how long `tak_tester.py` was left running |
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
| `postgres.buffers_backend` | count | blocks written by client backends: the sum of `writes` in `pg_stat_io` for `client backend` |
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

`<app>` is `takserver-messaging` or `takserver-api`. Run 39556568533 restarted messaging in 2m12s and the API in 1m52s on amd64. The probes poll every 10s, so Ready can lag the process by at most one period, about 8% of those restarts. `periodSeconds` stays 10. A class-data-sharing archive was not added: the class-loading share of that time is not in this record yet, and the archive would add bytes to both images for each arch. If `jvm_to_log_s` is most of the start on a later run, that archive is the next change.

Run 39556568533 measured the old scale-down on validate-install. amd64 job 119079081806 spent 103s in Helm and then 5m21s restarting config, messaging, api, and plugins. arm64 job 119079081713 spent 98s in Helm and then 5m08s. `startup.max_generation` and `startup.max_restart_count` are how a later run shows that second rollout is gone. This file does not store that later run.

A config dominates another on one view when it is better or equal on both
axes of that view and strictly better on one. The three views are footprint
against throughput, footprint against mean latency, and footprint against warm
rollout duration. arm64 and amd64 are
separate series on one scale per cohort and view, so a
circle can be compared across architectures. Dominance is still decided
inside one architecture. Dominated configs are marked in the job summary and
drawn as open circles in the SVG.

Counters are cleared with `pg_stat_reset()` and `pg_stat_reset_shared('bgwriter')`
just before the load, so they cover that run and not the install. A config
may set `postgres:` with those five parameters. The harness runs
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
