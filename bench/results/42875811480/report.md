# Benchmark front

Each workload cohort has one scale per view across architectures. Dominance is per architecture within a matched revision, client count and duration.
Cold install age is a shared reference in the evidence table, not a swept-config ranking. The readiness plot uses warm rollout duration only. Missing or invalid axes are not plotted. These are individual observations, not confidence intervals.

## Cohort: clients=50, duration=1200 s, revision=ceb901e139688b2258de1362a105ac5a569e94a9, protocol=synthetic-baseline-v1, warmup=300 s, self-SA=5 s

### amd64

#### footprint vs throughput

Front: baseline-r1, baseline-r2
Dominated: baseline-r3

#### footprint vs mean latency

Front: baseline-r1, baseline-r2
Dominated: baseline-r3

#### footprint vs warm rollout time

No config had both axes.

### arm64

#### footprint vs throughput

Front: baseline-r1, baseline-r2
Dominated: baseline-r3

#### footprint vs mean latency

Front: baseline-r2, baseline-r3
Dominated: baseline-r1

#### footprint vs warm rollout time

No config had both axes.

### Synthetic baseline repeats

One cluster per native architecture; these repeats share data/cache history and are not independent cluster replicates. Synthetic traffic is not production representative. Received messages include fan-out; offered self-SA updates and sent/received message rates have different semantics. Collection failures and workload-performance failures remain in the table and are excluded from the tuning front; low traffic or missing pongs can be genuine overload observations.

| Architecture | Repeat | Valid | Offered self-SA/s | Observed self-SA/s | Observed stable clients | Sent messages/s | Received messages/s | Actual measured seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amd64 | 1 | yes | 10.000 | 9.896 | 50 | 19.793 | 494.822 | 1200.461 |
| amd64 | 2 | yes | 10.000 | 9.896 | 50 | 19.790 | 494.721 | 1200.658 |
| amd64 | 3 | yes | 10.000 | 9.896 | 50 | 19.792 | 494.792 | 1200.579 |
| arm64 | 1 | yes | 10.000 | 9.910 | 50 | 19.821 | 495.630 | 1200.104 |
| arm64 | 2 | yes | 10.000 | 9.907 | 50 | 19.812 | 495.269 | 1200.107 |
| arm64 | 3 | yes | 10.000 | 9.907 | 50 | 19.817 | 495.294 | 1200.115 |

| Architecture | Valid repeats / planned | Received messages/s median [range] | Mean ping-pong ms median [range] |
| --- | --- | --- | --- |
| amd64 | 3 / 3 | 494.792 [494.721, 494.822] | 385.229 [374.255, 399.803] |
| arm64 | 3 / 3 | 495.294 [495.269, 495.630] | 452.877 [430.011, 470.297] |

### Observed load and footprint

| Architecture | Config | Steady working set (MiB) | Peak working set (MiB) | Steady CPU (m) | Received messages/s | Mean ping-pong (ms) | Cold install reference (s) | Warm rollout (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline-r1 | 3962.715 | 3964.004 | 221.450 | 494.822 | 374.255 | 170.000 | not measured |
| amd64 | baseline-r2 | 3950.566 | 3968.973 | 179.034 | 494.721 | 399.803 | 170.000 | not measured |
| amd64 | baseline-r3 | 4006.395 | 4006.758 | 272.956 | 494.792 | 385.229 | 170.000 | not measured |
| arm64 | baseline-r1 | 3912.352 | 3929.945 | 165.401 | 495.630 | 470.297 | 131.000 | not measured |
| arm64 | baseline-r2 | 3911.762 | 3948.566 | 137.958 | 495.269 | 452.877 | 131.000 | not measured |
| arm64 | baseline-r3 | 3967.723 | 3988.238 | 136.185 | 495.294 | 430.011 | 131.000 | not measured |

### Observed pod startup phases

These are the pods observed at each config's collection time. A database-only rollout can reuse an earlier TAK pod; these rows are not proof that each config independently measured both a cold and a warm TAK start. Container start includes entrypoint work and does not measure JVM start or class loading. Legacy jvm_to_log_s values also used container timestamps. Negative timings are invalid observations, not durations.

| Architecture | Config | App | Image pull (s) | Init containers (s) | Container start to first startup log (s) | Startup log to Ready (s) |
| --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline-r1 | takserver-messaging | 0.000 | wait-deps: 43.000; import-trust: 46.000; render-oidc: 0.000 | 59.113 | 7.887 |
| amd64 | baseline-r1 | takserver-api | 1.000 | wait-deps: 42.000; import-trust: 46.000; render-oidc: 0.000 | 74.462 | 3.538 |
| amd64 | baseline-r2 | takserver-messaging | 0.000 | wait-deps: 43.000; import-trust: 46.000; render-oidc: 0.000 | 59.113 | 7.887 |
| amd64 | baseline-r2 | takserver-api | 1.000 | wait-deps: 42.000; import-trust: 46.000; render-oidc: 0.000 | 74.462 | 3.538 |
| amd64 | baseline-r3 | takserver-messaging | 0.000 | wait-deps: 43.000; import-trust: 46.000; render-oidc: 0.000 | 59.113 | 7.887 |
| amd64 | baseline-r3 | takserver-api | 1.000 | wait-deps: 42.000; import-trust: 46.000; render-oidc: 0.000 | 74.462 | 3.538 |
| arm64 | baseline-r1 | takserver-messaging | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 44.059 | not measured |
| arm64 | baseline-r1 | takserver-api | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 52.637 | 2.363 |
| arm64 | baseline-r2 | takserver-messaging | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 44.059 | not measured |
| arm64 | baseline-r2 | takserver-api | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 52.637 | 2.363 |
| arm64 | baseline-r3 | takserver-messaging | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 44.059 | not measured |
| arm64 | baseline-r3 | takserver-api | 0.000 | wait-deps: 32.000; import-trust: 40.000; render-oidc: 0.000 | 52.637 | 2.363 |

### Postgres

Memory is sampled container working set, not process RSS. Database counters describe cot; checkpoints and backend writes are cluster-wide. A counter-reset error in the record caveats means the counters are not verified for this load window.

#### Load, cache and memory

| Architecture | Config | Hit ratio | Temp files | Temp bytes | Steady working set (MiB) | Peak working set (MiB) | Received messages/s | Mean ping-pong (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline-r1 | 1.000000 | 0.000 | 0.000 | 88.160 | 88.160 | 494.822 | 374.255 |
| amd64 | baseline-r2 | 1.000000 | 0.000 | 0.000 | 98.004 | 98.695 | 494.721 | 399.803 |
| amd64 | baseline-r3 | 1.000000 | 0.000 | 0.000 | 112.473 | 138.477 | 494.792 | 385.229 |
| arm64 | baseline-r1 | 1.000000 | 0.000 | 0.000 | 78.457 | 79.113 | 495.630 | 470.297 |
| arm64 | baseline-r2 | 1.000000 | 0.000 | 0.000 | 92.699 | 124.199 | 495.269 | 452.877 |
| arm64 | baseline-r3 | 1.000000 | 0.000 | 0.000 | 104.133 | 135.484 | 495.294 | 430.011 |

#### Checkpoints and backend writes

| Architecture | Config | Timed checkpoints | Requested checkpoints | Checkpoint write (ms) | Checkpoint sync (ms) | Backend write operations |
| --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline-r1 | 4.000 | 0.000 | 217520.000 | 68.000 | 11891.000 |
| amd64 | baseline-r2 | 4.000 | 0.000 | 286543.000 | 18.000 | 11898.000 |
| amd64 | baseline-r3 | 4.000 | 0.000 | 364468.000 | 18.000 | 11905.000 |
| arm64 | baseline-r1 | 4.000 | 0.000 | 239555.000 | 32.000 | 11923.000 |
| arm64 | baseline-r2 | 4.000 | 0.000 | 275390.000 | 37.000 | 11918.000 |
| arm64 | baseline-r3 | 4.000 | 0.000 | 365037.000 | 23.000 | 11923.000 |

#### Observed settings

| Architecture | Config | shared_buffers | work_mem | effective_cache_size | max_wal_size | checkpoint_timeout |
| --- | --- | --- | --- | --- | --- | --- |
| amd64 | baseline-r1 | 128MB | 4MB | 4GB | 1GB | 5min |
| amd64 | baseline-r2 | 128MB | 4MB | 4GB | 1GB | 5min |
| amd64 | baseline-r3 | 128MB | 4MB | 4GB | 1GB | 5min |
| arm64 | baseline-r1 | 128MB | 4MB | 4GB | 1GB | 5min |
| arm64 | baseline-r2 | 128MB | 4MB | 4GB | 1GB | 5min |
| arm64 | baseline-r3 | 128MB | 4MB | 4GB | 1GB | 5min |

### Record caveats

No collection errors were recorded. This does not establish comparability beyond the stored metadata.
