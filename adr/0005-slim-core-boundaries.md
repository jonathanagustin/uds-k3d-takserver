# 5. Stay inside what slim UDS Core and the stock chart provide

Date: 2026-10-18

## Status

Accepted

## Context

The tested bundle is `k3d-core-slim-dev`, which installs `core-base` (Istio, the UDS operator, Pepr) and `core-identity-authorization` (Keycloak, Authservice). The standard `core` package is the one that adds Vector, Loki, Prometheus, and optional Velero. The stock TAK chart has no `securityContext` values and no Prometheus port. The metrics port is added at admission time. See [ADR 0016](0016-prometheus-monitors.md).

## Decision

- Package `monitor` entries for the API and messaging metrics ports, and a PodMonitor for the Pepr module, only when `monitoring.coreos.com/v1` is installed. Slim omits them. See [ADR 0016](0016-prometheus-monitors.md).
- No log agent in this package. TAK logs to stdout. The test requires that stream. A Loki query runs only when a Loki Service exists. Slim-dev does not install one.
- No Velero objects on the slim bundle. The full bundle installs `core-backup-restore` and a logical database dump. See [ADR 0016](0016-logical-db-dump.md) and [Data](../docs/data.md).
- No `runAsNonRoot` or read-only root filesystem. The upstream Deployments cannot express that, and TAK writes `/certs`, `/logs`, and `/conf`.
- Per-workload, per-port allow rules cover Postgres, NATS, Ignite, and the TAK processes. There is no namespace-wide allow rule. See [ADR 0007](0007-per-workload-network-rules.md). Keycloak egress is only the API and messaging selectors to the tenant gateway on port 443. There is no `remoteGenerated: Anywhere`.

## Consequences

Prometheus, cluster log search, and scheduled backups come from the standard core package. This package exports metrics for that Prometheus to scrape when it is installed. A cluster that installs the logging and backup layers collects TAK stdout and can back up the namespace. This package does not grow a sidecar or a forked Deployment to imitate those features.

The per-PR gate stays on the slim bundle. The functional layers run in a separate workflow, on main, nightly, and on pull requests labeled `full-core`. See [ADR 0015](0015-full-core-is-a-scheduled-gate.md).
