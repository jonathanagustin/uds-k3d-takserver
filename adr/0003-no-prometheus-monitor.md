# 3. Do not add a Package monitor

Date: 2026-10-18

## Status

Superseded by [ADR 0017](0017-prometheus-monitors.md)

## Context

UDS Package `monitor` entries become ServiceMonitors. TAK Server 5.7-RELEASE-14 sets `management.endpoints.web.exposure.include=*` and depends on Spring Actuator, Micrometer, and `micrometer-registry-cloudwatch2`. The Gradle files do not depend on `micrometer-registry-prometheus`. Actuator is served on the Marti HTTPS connectors. Port 8443 requires a client certificate. The API Service ports are 8443, 8444, and 8446.

## Decision

The Package has no `monitor` block. A ServiceMonitor would have nothing in Prometheus text format to scrape, and it would have to present a TAK client certificate to do it.

## Consequences

Cluster metrics for TAK are not part of this package. Adding a monitor later means a Prometheus registry in the image, a port that does not require a client certificate, and a `monitor` entry with a selector, port, path, and description.
