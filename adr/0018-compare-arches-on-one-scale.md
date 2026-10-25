# 18. Compare amd64 and arm64 on one scale

Date: 2026-10-25

## Status

Accepted

## Context

[ADR 10](0010-amd64-and-arm64.md) builds, packages, and tests both architectures. The open question is which one reaches a given throughput with less RSS, whether startup differs, and whether the arm64 CI speed is the runner or TAK itself.

`bench/report.py` already keeps a Pareto front per architecture. The SVG used to scale each architecture on its own. One point then sat in the middle of the panel, and the lowest footprint on each architecture sat on the same left edge, so the two series could not be read against each other.

There is no completed nightly load artifact to cite. RSS, throughput, and latency per architecture are still unmeasured. The CI timings collected so far are job durations, not a TAK load. Issue #198 tracks the missing run. `gc-serial` stays skipped. The configs a completed run needs are `baseline`, `heap-768`, and `postgis-memory`, on both architectures, at the same client count.

## Decision

- Each SVG view uses one scale for every architecture in the input. A smaller footprint is to the left. Filled circles are on that architecture's front. Open circles are dominated inside that architecture.
- An arm64 point does not knock an amd64 point off the front, or the reverse. The markdown report stays grouped by architecture and says the plot is shared.
- This decision does not pick an architecture for dev, CI, or deploy. Both stay supported. A recommendation waits on a Benchmark run that records those configs on both architectures.

## Consequences

- The next completed Benchmark artifact can be compared on the plot without another change to the scaler.
- Job-time differences are not a reason to drop an architecture from the matrix.
- [ADR 10](0010-amd64-and-arm64.md) is unchanged.
