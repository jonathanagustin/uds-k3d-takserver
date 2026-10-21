# 12. Standard TAK ports on the passthrough gateway

Date: 2026-10-21

## Status

Accepted

## Context

TAK clients keep one server host. ATAK enrolls for a certificate at `<host>:<apiCertEnrollmentPort>` (default 8446) and opens the streaming connection at `<host>:8089`. The UDS Package CR exposes services on the gateways' port 443 only, routed by SNI, so each TAK port gets its own host (`takserver` for 8446, `takserver-stream` for 8089). With those routes, no single host reaches both ports, and a stock client cannot enroll and then connect.

The UDS Core passthrough Gateway is rendered by `uds-istio-config` with servers on 80 and 443 only, and that chart has no value for extra servers. The Istio gateway chart that runs the pods does take a `service.ports` list, and its NetworkPolicy opens every listed port.

## Decision

The bundle overrides `istio-passthrough-gateway.gateway` `service.ports` to publish 8446 and 8089 in addition to the upstream defaults. The chart adds its own Istio Gateway that selects the passthrough gateway pods, with a TLS passthrough server on 8446 and a TCP server on 8089 for the hosts in `standardPorts.hosts`, and a VirtualService that routes 8446 by port and SNI to the API Service and 8089 by port alone to the messaging Service. ATAK's streaming library sends no SNI, so 8089 cannot depend on it ([ADR 13](0013-atak-test-device-in-kubevirt.md) found this with a real device). TLS is still end to end on both ports. The 443 SNI routes do not change.

## Consequences

- A stock TAK client can use one host for enrollment and streaming, as with a TAK Server outside Kubernetes.
- The traffic reaches the same Service ports as the Package expose entries, so the operator's NetworkPolicies already allow it. No rule is added.
- Two Istio objects live outside the Package CR. The UDS operator does not manage or validate them.
- The `service.ports` override replaces the chart's list, so it repeats the upstream defaults. A UDS Core upgrade that changes those defaults needs the same change here.
- Inside the cluster, `takserver.<domain>` still resolves to the tenant gateway, so in-cluster clients use `takserver-stream.<domain>` on 8446 and 8089.
- k3d does not map host ports 8446 and 8089. Tests port-forward the gateway Service.
