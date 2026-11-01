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
| `time_to_ready.cold_s` | seconds | Ready condition minus pod creation, for the install's pods. Null when a pod has restarted |
| `time_to_ready.warm_s` | seconds | rollout restart of the TAK Deployments until Ready. Null for the baseline, which keeps the cold pods |
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
| `errors` | strings | why a null field was not measured |

Throughput in the Pareto report is `messages_received / duration_s`. The
latency axis is `ping_pong_ms_mean`, not a p95. Footprint is
`kubelet.steady_rss_bytes`. Ready time is `warm_s` when it was measured and
`cold_s` otherwise.

A config dominates another on one view when it is better or equal on both
axes of that view and strictly better on one. The three views are footprint
against throughput, footprint against mean latency, and footprint against
ready time. arm64 and amd64 are separate series on one scale per view, so a
circle can be compared across architectures. Dominance is still decided
inside one architecture. Dominated configs are marked in the job summary and
drawn as open circles in the SVG.

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
