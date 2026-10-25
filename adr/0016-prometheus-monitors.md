# 16. Scrape TAK and the Pepr module on a separate port

Date: 2026-10-25

## Status

Accepted

Supersedes [ADR 0003](0003-no-prometheus-monitor.md).

## Context

TAK Server 5.7-RELEASE-14 exposes Actuator and Micrometer, and it ships `micrometer-registry-cloudwatch2` rather than `micrometer-registry-prometheus`. Actuator is on the Marti connectors. Port 8443 requires a client certificate. The Package `monitor` block has a path and a named port, and it has no scheme or TLS settings, so it cannot scrape that connector.

The API process builds its Tomcat connectors from CoreConfig. That factory is the main server. Spring Boot still starts a second server when `management.server.port` is set, and that server does not copy `server.ssl`. Messaging has no custom factory. Both processes can take the registry from jars on `loader.path` without a TAK source change.

The `takserver-oidc` module serves `/metrics` on HTTPS port 3000. The generated chart can enable a ServiceMonitor, and that selector is every admission controller in `pepr-system`. The container port is unnamed.

Postgres and NATS do not expose Prometheus text unless an exporter sidecar is turned on. Those images are not built here.

## Decision

- The API and messaging images carry `micrometer-registry-prometheus` 1.13.8 and the Prometheus client 1.2.1 jars it loads, under `/opt/tak/metrics`. Their cluster scripts add `-Dloader.path=/opt/tak/metrics` and `-Dmanagement.server.port=9100`. The management listener is plain HTTP. Config and plugins do not get those flags.
- The admission module adds container port `metrics` on 9100 to the API and messaging pods. The upstream chart cannot.
- When `monitoring.coreos.com/v1` is installed, the Package has PodMonitor entries for those two pods, path `/actuator/prometheus`. The operator creates the PodMonitors and the policy that lets Prometheus in `monitoring` reach port 9100. Slim does not have the API, so the block is omitted.
- The chart adds PodMonitor `takserver-oidc` for pods `app=takserver-oidc` in `pepr-system`, HTTPS, `insecureSkipVerify`, path `/metrics`. It does not select the Pepr pod with a NetworkPolicy.
- Postgres and NATS exporters stay off.

## Consequences

A full core install can scrape `jvm_memory_used_bytes` from the API and messaging pods, and `pepr_errors` from the admission module. The dashboard and the heap alert use those names. Slim still deploys, and it still has no monitors.

`management.server.port` is not a TAK setting. If a future TAK release starts the management listener on the CoreConfig connectors, the targets stay down until that release is handled on its own. Replacing `spring.autoconfigure.exclude` repeats the Mongo excludes from `application.properties`. Dropping one of them would let Mongo auto-configuration run.

Port 9100 is not on a Service or a gateway. `flows.py` only records connections whose other end is a pod in `takserver`, so the scrape from `monitoring` is not an in-namespace flow.
