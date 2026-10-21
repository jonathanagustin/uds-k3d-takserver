# 5. Stay inside what slim UDS Core and the stock chart provide

Date: 2026-10-18

## Status

Accepted

## Context

The tested bundle is `k3d-core-slim-dev`, which installs `core-base` (Istio, Keycloak, Pepr). The standard `core` package is the one that adds Vector, Loki, Prometheus, and optional Velero. The stock TAK chart has no `securityContext` values and no Prometheus port. TAK 5.7-RELEASE-14 does not depend on `micrometer-registry-prometheus`.

## Decision

- No Package `monitor` entry and no scrape allow rule. A ServiceMonitor would not receive Prometheus text. See [ADR 0003](0003-no-prometheus-monitor.md).
- No log agent in this package. TAK logs to stdout. The test requires that stream. A Loki query runs only when a Loki Service exists. Slim-dev does not install one.
- No Velero objects. Backup notes for the Postgres volume and ConfigMap `cert-migration` are in [Data](../docs/data.md). Enable Velero from the standard core package when a cluster needs it.
- No `runAsNonRoot` or read-only root filesystem. The upstream Deployments cannot express that, and TAK writes `/certs`, `/logs`, and `/conf`.
- Per-workload, per-port allow rules cover Postgres, NATS, Ignite, and the TAK processes. There is no namespace-wide allow rule. See [ADR 0007](0007-per-workload-network-rules.md). Keycloak egress is only the API and messaging selectors to the tenant gateway on port 443. There is no `remoteGenerated: Anywhere`.

## Consequences

Metrics, cluster log search, and scheduled backups are properties of the standard core package, not of this one. A cluster that installs that package collects TAK stdout and can back up the namespace. This package does not grow a sidecar or a forked Deployment to imitate those features.
