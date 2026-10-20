# Networking

The UDS operator turns the Package `network` block into NetworkPolicy and Istio resources. The rules are in `chart/templates/uds-package.yaml`. The one Istio object this package ships itself is the DestinationRule described in [Tenant gateway to 8447](#tenant-gateway-to-8447).

## Exposure

The upstream chart's nginx ingress stays off. The Package exposes the same three ports on the passthrough gateway. Passthrough forwards raw TLS. Istio does not terminate it.

| Host | Gateway | Service | Port | Why this port |
| --- | --- | --- | --- | --- |
| `takserver.<domain>` | tenant | `takserver-web` | 8447 | Browser UI. The gateway ends browser TLS and opens a new TLS connection to the pod. `clientAuth` off, admin UI and WebTAK on. |
| `takserver.<domain>` | passthrough | `takserver-api-service` | 8446 | Certificate enrollment and the OIDC discovery document. Admin UI and WebTAK are off. |
| `takserver-api.<domain>` | passthrough | `takserver-api-service` | 8443 | Upstream `tak-api-cert`. The connector requires a client certificate. |
| `takserver-stream.<domain>` | passthrough | `takserver-messaging-service` | 8089 | Upstream streaming ingress. ATAK usually dials 8089. Here that listener is SNI on the passthrough gateway. |

Ports 8444, 9000, and 9001 stay on the Services and have no gateway host. TLS on 8089, 8443, 8444, 8446, 9000, and 9001 is not terminated by the tenant gateway. Messaging also binds plaintext 8080, and the actuator is on that port. No Service in this package publishes 8080, and AuthorizationPolicy `takserver-deny-plaintext-8080` denies it to messaging, the API, and Ignite. `k3d-core-slim-dev` does not select `istio-passthrough-gateway`. `bundle/uds-bundle.yaml` turns that optional component on for tests.

On k3d, host port 443 is the tenant gateway. Tests port-forward `svc/passthrough-ingressgateway` in `istio-passthrough-gateway` and send SNI to that local port.

## Tenant gateway to 8447

The Package CR `expose` entry cannot ask the gateway to use TLS toward the Service. The chart adds that part as plain Istio, outside the Package CR, when `api.web.backendTLS.enabled` is `true` (the default):

- The 8447 connector serves TLS from `certs/files/takserver-web.jks`. The cert Job issues it from the deploy-time CA, with the names `takserver-web`, `takserver-web.takserver`, `takserver-web.takserver.svc`, and `takserver-web.takserver.svc.cluster.local`.
- Service `takserver-web` port is `https` with `appProtocol: https`.
- DestinationRule `takserver-web` sets TLS mode `SIMPLE` on port 8447 with SNI `takserver-web.takserver.svc.cluster.local`, the same expected name, and `credentialName: takserver-web-ca`. It is exported only to `istio-tenant-gateway`. `insecureSkipVerify` is not set.
- A Zarf deploy action copies `ca.pem` from ConfigMap `cert-migration` into Secret `takserver-web-ca` (key `cacert`) in `istio-tenant-gateway`. A gateway reads `credentialName` only from its own namespace. The CA key is not copied.

In ambient mode the gateway's TLS connection still travels inside HBONE, so strict mTLS still applies. TAK then reports no non-secure ports and marks its cookies Secure. The trade-offs are in [ADR 0006](../adr/0006-re-encrypt-gateway-traffic-to-tak.md).

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

No waypoint is configured. The Package service mesh field only selects `ambient` or `sidecar`. A waypoint is what Authservice adds, and Authservice is off. Ports 8443, 8446, and 8089 are passthrough TLS, including client certificates, so a waypoint must not terminate them. Port 8447 is TLS from the tenant gateway to the pod, carried inside the HBONE tunnel. ztunnel forwards that connection. The smoke and UI tasks then open all four routes.

The upstream database Job sets `proxy.istio.io/config`. UDS `RestrictIstioSidecarOverrides` denies that annotation. Exemption `takserver-db-setup` in `uds-policy-exemptions` allows only that policy for pods named `takserver-db-setup-*`. The cert Job does not set an Istio annotation. The OIDC init container is added to the existing TAK pods and does not set one either.

`sso.uds.dev` resolves to `127.0.0.1` from the dev DNS, including inside a pod. The API Deployment's hostAlias sends that name to the ClusterIP of `tenant-ingressgateway` in `istio-tenant-gateway`. The Istio 1.31 gateway chart labels those pods `app: tenant-ingressgateway` and `istio: tenant-ingressgateway`.
