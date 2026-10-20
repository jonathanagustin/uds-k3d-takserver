# Networking

The UDS operator turns the Package `network` block into NetworkPolicy and Istio resources. This package does not ship those objects itself. The rules are in `chart/templates/uds-package.yaml`.

## Exposure

The upstream chart's nginx ingress stays off. The Package exposes the same three ports on the passthrough gateway. Passthrough forwards raw TLS. Istio does not terminate it.

| Host | Gateway | Service | Port | Why this port |
| --- | --- | --- | --- | --- |
| `takserver.<domain>` | tenant | `takserver-web` | 8447 | Browser UI. TLS ends at the gateway. The connector is plaintext, `clientAuth` off, admin UI and WebTAK on. |
| `takserver.<domain>` | passthrough | `takserver-api-service` | 8446 | Certificate enrollment and the OIDC discovery document. Admin UI and WebTAK are off. |
| `takserver-api.<domain>` | passthrough | `takserver-api-service` | 8443 | Upstream `tak-api-cert`. The connector requires a client certificate. |
| `takserver-stream.<domain>` | passthrough | `takserver-messaging-service` | 8089 | Upstream streaming ingress. ATAK usually dials 8089. Here that listener is SNI on the passthrough gateway. |

Ports 8444, 9000, and 9001 stay on the Services and have no gateway host. TLS on 8089, 8443, 8444, 8446, 9000, and 9001 is not terminated by the tenant gateway. Messaging also binds plaintext 8080, and the actuator is on that port. No Service in this package publishes 8080, and AuthorizationPolicy `takserver-deny-plaintext-8080` denies it to messaging, the API, and Ignite. `k3d-core-slim-dev` does not select `istio-passthrough-gateway`. `bundle/uds-bundle.yaml` turns that optional component on for tests.

On k3d, host port 443 is the tenant gateway. Tests port-forward `svc/passthrough-ingressgateway` in `istio-passthrough-gateway` and send SNI to that local port.

## Allow rules

Every allow rule has its own description. Pepr names the NetworkPolicy from that description, so two rules that share a description collide.

| Direction | Scope | Description |
| --- | --- | --- |
| Ingress | `remoteGenerated: IntraNamespace` | Ingress from TAK processes, Postgres, NATS, and Ignite in this namespace |
| Egress | `remoteGenerated: IntraNamespace` | Egress to TAK processes, Postgres, NATS, and Ignite in this namespace |
| Egress | `remoteGenerated: KubeAPI`, one rule per pod label in `kubeApi.selectors` | Ignite Kubernetes discovery for that label |
| Egress | namespace `istio-tenant-gateway`, labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway`, port 443, API selector, only when `sso.enabled` | Keycloak discovery, token, and JWKS |

Postgres, NATS, and Ignite are installed in the `takserver` namespace by the upstream chart. Intra-namespace is the allow boundary for those processes and for Postgres port 5432. Ignite also has explicit rules both ways between `takserver-ignite` and the API, messaging, config, and plugins pods on 47100, 47500, and 10800. A missing return path stalls until `igniteConnectionTimeoutSeconds` (300) before the client falls back. Keycloak is not in the namespace. The API selector's only external allow is port 443 on the tenant gateway, which fronts discovery, the token endpoint, and JWKS. There is no `remoteGenerated: Anywhere` rule and no Prometheus scrape rule. TAK does not expose a Prometheus endpoint, so nothing is opened for a scraper. See [ADR 0003](../adr/0003-no-prometheus-monitor.md).

The Ignite chart and the API, messaging, config, and plugins Deployments use ServiceAccount `takserver-ignite`. Each of those pod labels needs its own Kubernetes API rule. One rule limited to `app: takserver-ignite` drops the clients' API calls during the TLS handshake.

`additionalNetworkAllow` appends deployer rules. Each entry needs a unique `description`.

## Mesh

`network.serviceMesh.mode` is `ambient`. The operator labels namespace `takserver` with `istio.io/dataplane-mode=ambient` and does not inject `istio-proxy`. The package does not set `sidecar.istio.io/inject` or `istio-injection=enabled`. The test task requires that label and rejects an `istio-proxy` or `istio-validation` container before the gateway checks.

No waypoint is configured. The Package service mesh field only selects `ambient` or `sidecar`. A waypoint is what Authservice adds, and Authservice is off. Ports 8443, 8446, and 8089 are passthrough TLS, including client certificates, so a waypoint must not terminate them. Port 8447 is HTTP from the tenant gateway to the pod. ztunnel forwards that connection. The smoke and UI tasks then open all four routes.

The upstream database Job sets `proxy.istio.io/config`. UDS `RestrictIstioSidecarOverrides` denies that annotation. Exemption `takserver-db-setup` in `uds-policy-exemptions` allows only that policy for pods named `takserver-db-setup-*`. The cert Job does not set an Istio annotation. The OIDC init container is added to the existing TAK pods and does not set one either.

`sso.uds.dev` resolves to `127.0.0.1` from the dev DNS, including inside a pod. The API Deployment's hostAlias sends that name to the ClusterIP of `tenant-ingressgateway` in `istio-tenant-gateway`. The Istio 1.31 gateway chart labels those pods `app: tenant-ingressgateway` and `istio: tenant-ingressgateway`.
