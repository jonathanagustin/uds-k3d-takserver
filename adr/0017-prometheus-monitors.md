# 17. Scrape TAK and the Pepr module on a separate port

Date: 2026-10-25

## Status

Accepted

Supersedes [ADR 0003](0003-no-prometheus-monitor.md).

## Context

TAK Server 5.7-RELEASE-14 exposes Actuator and Micrometer, and it ships `micrometer-registry-cloudwatch2` rather than `micrometer-registry-prometheus`. Actuator is on the Marti connectors. Port 8443 requires a client certificate. The Package `monitor` block has a path and a named port, and it has no scheme or TLS settings, so it cannot scrape that connector.

A first attempt put `micrometer-registry-prometheus` on `loader.path` and moved Actuator to `management.server.port`. The API started, but messaging exited: its `MessagingOnlyConfiguration` web server factory cannot be instantiated in the child management context (`MessagingOnlyConfiguration$1 cannot be instantiated`). A second Spring server is not something TAK supports.

The Prometheus JMX exporter javaagent runs its own HTTP server inside the JVM and reads the JVM through JMX. It needs no change to TAK's Spring configuration, classpath, or connectors. A sidecar exporter would need remote JMX opened on each TAK JVM, which is another listener and more configuration.

The `takserver-oidc` module serves `/metrics` on HTTPS port 3000. The generated chart can enable a ServiceMonitor, and that selector is every admission controller in `pepr-system`. The container port is unnamed.

Postgres and NATS do not expose Prometheus text unless an exporter sidecar is turned on. Those images are not built here.

## Decision

- The API and messaging images carry `jmx_prometheus_javaagent` 1.7.0 (sha256-checked) and `/opt/tak/metrics/jmx-exporter.yaml`. Their cluster scripts add `-javaagent:...=9100:/opt/tak/metrics/jmx-exporter.yaml` and `-Dserver.tomcat.mbeanregistry.enabled=true` to the `java` command. The exporter serves plain HTTP on 9100. Config and plugins do not get the agent.
- The exporter config reads only Tomcat's `GlobalRequestProcessor` MBeans (`tomcat_requestcount_total`, `tomcat_errorcount_total`). The agent's built-in collectors add `jvm_*` and `process_*`. Ignite's MBeans are not scraped.
- The admission module adds container port `metrics` on 9100 to the API and messaging pods. The upstream chart cannot.
- When `monitoring.coreos.com/v1` is installed, the Package has PodMonitor entries for those two pods, path `/metrics`. The operator creates the PodMonitors and the policy that lets Prometheus in `monitoring` reach port 9100. Slim does not have the API, so the block is omitted.
- The chart adds PodMonitor `takserver-oidc` for pods `app=takserver-oidc` in `pepr-system`, HTTPS, `insecureSkipVerify`, path `/metrics`. It does not select the Pepr pod with a NetworkPolicy.
- Postgres and NATS exporters stay off.

## Consequences

A full core install can scrape `jvm_memory_used_bytes`, `jvm_gc_collection_seconds_count`, and `tomcat_requestcount_total` from the API and messaging pods, and `pepr_errors` from the admission module. The dashboard and the heap alert use those names. Slim still deploys, and it still has no monitors.

The metric names are the JMX exporter's, not Micrometer's: there is no `http_server_requests_seconds` histogram, only Tomcat's request and error counters per connector. The agent adds a small HTTP server thread to each JVM. Upgrading the agent means a new jar checksum in the Dockerfile.

Port 9100 is not on a Service or a gateway. `flows.py` only records connections whose other end is a pod in `takserver`, so the scrape from `monitoring` is not an in-namespace flow.
