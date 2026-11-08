# Benchmark front

Each workload cohort has one scale per view across architectures. Dominance is per architecture within a matched revision, client count and duration.
Cold install age is a shared reference in the evidence table, not a swept-config ranking. The readiness plot uses warm rollout duration only. Missing or invalid axes are not plotted. These are individual observations, not confidence intervals.

## Cohort: clients=10, duration=60 s, revision=68b44db46326285f6533d1ff4dd59a410f20b6c1

### amd64

#### footprint vs throughput

Front: postgis-buffers, postgis-wal
Dominated: baseline

#### footprint vs mean latency

Front: postgis-buffers, postgis-wal
Dominated: baseline

#### footprint vs warm rollout time

Front: postgis-buffers, postgis-wal
Dominated: none

### arm64

#### footprint vs throughput

Front: postgis-buffers
Dominated: baseline, postgis-wal

#### footprint vs mean latency

Front: postgis-buffers, postgis-wal
Dominated: baseline

#### footprint vs warm rollout time

Front: postgis-buffers, postgis-wal
Dominated: none

### Observed load and footprint

| Architecture | Config | Steady working set (MiB) | Peak working set (MiB) | Steady CPU (m) | Received messages/s | Mean ping-pong (ms) | Cold install reference (s) | Warm rollout (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline | 3737.707 | 3744.297 | 227.902 | 20.233 | 13.155 | not measured | not measured |
| amd64 | postgis-buffers | 3572.480 | 3572.480 | 217.488 | 23.400 | 12.351 | not measured | 21.773 |
| amd64 | postgis-wal | 3699.934 | 3706.777 | 194.219 | 23.417 | 5.594 | not measured | 11.707 |
| arm64 | baseline | 3719.941 | 3719.941 | 752.801 | 20.233 | 8.501 | not measured | not measured |
| arm64 | postgis-buffers | 3524.430 | 3527.051 | 182.796 | 23.417 | 6.795 | not measured | 12.304 |
| arm64 | postgis-wal | 3689.984 | 3716.895 | 147.620 | 23.417 | 5.962 | not measured | 11.790 |

### Observed pod startup phases

These are the pods observed at each config's collection time. A database-only rollout can reuse an earlier TAK pod; these rows are not proof that each config independently measured both a cold and a warm TAK start. Negative timings are invalid observations, not durations.

| Architecture | Config | App | Image pull (s) | Init containers (s) | JVM to first startup log (s) | Startup log to Ready (s) |
| --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline | takserver-messaging | 0.000 | wait-deps: 64.000; import-trust: 42.000; render-oidc: 0.000 | 58.587 | 1.413 |
| amd64 | baseline | takserver-api | 0.000 | wait-deps: 94.000; import-trust: 43.000; render-oidc: 0.000 | 69.088 | 1.912 |
| amd64 | postgis-buffers | takserver-messaging | 0.000 | wait-deps: 4.000; import-trust: 42.000; render-oidc: 0.000 | 49.610 | 1.390 |
| amd64 | postgis-buffers | takserver-api | 0.000 | wait-deps: 33.000; import-trust: 42.000; render-oidc: 0.000 | 66.302 | 5.698 |
| amd64 | postgis-wal | takserver-messaging | 0.000 | wait-deps: 4.000; import-trust: 42.000; render-oidc: 0.000 | 49.610 | 1.390 |
| amd64 | postgis-wal | takserver-api | 0.000 | wait-deps: 33.000; import-trust: 42.000; render-oidc: 0.000 | 66.302 | 5.698 |
| arm64 | baseline | takserver-messaging | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 41.658 | 4.342 |
| arm64 | baseline | takserver-api | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 50.523 | 4.477 |
| arm64 | postgis-buffers | takserver-messaging | 0.000 | wait-deps: 3.000; import-trust: 40.000; render-oidc: 0.000 | 41.128 | 2.872 |
| arm64 | postgis-buffers | takserver-api | 0.000 | wait-deps: 33.000; import-trust: 40.000; render-oidc: 0.000 | 50.611 | 3.389 |
| arm64 | postgis-wal | takserver-messaging | 0.000 | wait-deps: 3.000; import-trust: 40.000; render-oidc: 0.000 | 41.128 | 2.872 |
| arm64 | postgis-wal | takserver-api | 0.000 | wait-deps: 33.000; import-trust: 40.000; render-oidc: 0.000 | 50.611 | 3.389 |

### Postgres

- amd64 baseline: hit_ratio 1.0, temp_bytes 0, checkpoints_req 0, rss 74612736, throughput 20.233, shared_buffers 128MB
- amd64 postgis-buffers: hit_ratio 0.953296, temp_bytes 0, checkpoints_req 0, rss 39501824, throughput 23.4, shared_buffers 128MB
- amd64 postgis-wal: hit_ratio 0.95486, temp_bytes 0, checkpoints_req 0, rss 33718272, throughput 23.417, shared_buffers 64MB
- arm64 baseline: hit_ratio 1.0, temp_bytes 0, checkpoints_req 0, rss 75198464, throughput 20.233, shared_buffers 128MB
- arm64 postgis-buffers: hit_ratio 0.950537, temp_bytes 0, checkpoints_req 0, rss 39428096, throughput 23.417, shared_buffers 128MB
- arm64 postgis-wal: hit_ratio 0.967577, temp_bytes 0, checkpoints_req 0, rss 34230272, throughput 23.417, shared_buffers 64MB

### Record caveats

- amd64 baseline: cloudtak-6f9f67877f-sdrd6 restarted, so this is not a cold start
- arm64 baseline: cloudtak-8477c757bc-nz52m restarted, so this is not a cold start
