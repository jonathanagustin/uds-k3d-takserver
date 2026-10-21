# Networking

The UDS operator turns the Package `network` block into NetworkPolicy and Istio resources. The rules are in `chart/templates/uds-package.yaml`. This package ships its own Istio objects only for the DestinationRule described in [Tenant gateway to 8447](#tenant-gateway-to-8447) and for the [standard TAK ports](#standard-tak-ports).

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

### Standard TAK ports

A field client such as ATAK enrolls at `<host>:8446` and then streams to the same `<host>:8089`, with the port taken from its settings and the host shared. The 443 routes above give each port its own host, so a client cannot use them with one server entry. `chart/templates/standard-ports.yaml` adds an Istio Gateway on the passthrough gateway pods with a TLS passthrough listener on 8446 and a TCP listener on 8089, and a VirtualService that sends 8446 to `takserver-api-service:8446`, matching on port and SNI (hosts in `standardPorts.hosts`, default `takserver` and `takserver-stream`), and 8089 to `takserver-messaging-service:8089`, matching on port alone. ATAK's streaming library does not send SNI, so an SNI match on 8089 would drop it. TLS still runs end to end on 8089 and TAK still requires the client certificate. The 443 routes stay as they are.

See [ADR 0012](../adr/0012-standard-tak-ports-on-the-passthrough-gateway.md). The gateway Service publishes the two ports through the bundle override `istio-passthrough-gateway.gateway` `service.ports` in `bundle/uds-bundle.yaml`. The Istio gateway chart's NetworkPolicy opens every port in that list. Traffic to TAK uses the same Service ports as the Package expose entries, so the operator's ingress rules for 8446 and 8089 already cover it and no rule is added. Set `standardPorts.enabled: false` to drop the listeners. Without the Service ports they are inert.

Inside the cluster, `takserver.<domain>` resolves to the tenant gateway (see [In-cluster DNS](#in-cluster-dns)), so in-cluster clients use `takserver-stream.<domain>:8446` and `:8089`. Outside the cluster, point the TAK host at the passthrough gateway's load balancer. On k3d, host ports 8446 and 8089 are not mapped. Tests port-forward them (`uds run test:gateway` writes `/tmp/tak-std-ports`), and `tests/api-smoke.sh` enrolls a certificate on 8446, streams a CoT event on 8089 with it, and waits for the client in `/Marti/api/clientEndPoints` as seen by that user. That list only shows clients that share a group with the caller, and the admin certificate has none.

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
| Egress and Ingress | API, messaging, plugins, and the `takserver-db-setup` Job to Postgres, port 5432 | `Egress 5432 from <client> to postgres`, `Ingress 5432 to postgres from <client>` |
| Egress and Ingress | API, messaging, and plugins to NATS, port 4222 | `Egress 4222 from <client> to nats`, `Ingress 4222 to nats from <client>` |
| Egress and Ingress | Ignite to Ignite, ports 47100 and 47500 | `Egress <port> from takserver-ignite to ignite-peers`, and the Ingress rule |
| Egress and Ingress | every pair of API, messaging, config, and plugins, port 47100 | `Egress 47100 from <a> to <b>`, `Ingress 47100 to <b> from <a>` |
| Egress | `remoteGenerated: KubeAPI`, one rule per pod label in `kubeApi.selectors` | Ignite Kubernetes discovery for that label |
| Egress | namespace `istio-tenant-gateway`, labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway`, port 443, API selector, only when `sso.enabled` | Keycloak discovery, token, and JWKS |
| Egress | namespace `istio-tenant-gateway`, labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway`, port 443, messaging selector, only when `sso.enabled` | Keycloak discovery and JWKS for 8089 clients |

Postgres, NATS, and Ignite are installed in the `takserver` namespace by the upstream chart. There is no namespace-wide allow rule. Each pod-to-pod flow is its own rule pair, from `intraNamespace` in `chart/values.yaml`: an Egress rule on the client and an Ingress rule on the server, both limited to the port. The list comes from `tests/flows.py`, which reads `/proc/net/tcp` in every pod and maps each connection to a client pod, a server pod, and a port. Task `test:flows` runs it after the other tests and fails when a connection has no rule. The config pod holds no Postgres or NATS connection, so it is not a client of either. See [ADR 0007](../adr/0007-per-workload-network-rules.md). Ignite also has explicit rules both ways between `takserver-ignite` and the API, messaging, config, and plugins pods on 47100, 47500, and 10800. A missing return path stalls until `igniteConnectionTimeoutSeconds` (300) before the client falls back. Keycloak is not in the namespace. The API and messaging selectors' only external allow is port 443 on the tenant gateway, which fronts discovery, the token endpoint, and JWKS. Messaging needs it because a certificate enrolled with a Keycloak token is checked against the issuer again when the client connects on 8089 (`X509Authenticator` calls the OAuth authenticator). Without it the TLS handshake completes and TAK then drops the client. There is no `remoteGenerated: Anywhere` rule and no Prometheus scrape rule. TAK does not expose a Prometheus endpoint, so nothing is opened for a scraper. See [ADR 0003](../adr/0003-no-prometheus-monitor.md).

The Ignite chart and the API, messaging, config, and plugins Deployments use ServiceAccount `takserver-ignite`. Each of those pod labels needs its own Kubernetes API rule. One rule limited to `app: takserver-ignite` drops the clients' API calls during the TLS handshake.

`additionalNetworkAllow` appends deployer rules. Each entry needs a unique `description`.

## Mesh

`network.serviceMesh.mode` is `ambient`. The operator labels namespace `takserver` with `istio.io/dataplane-mode=ambient` and does not inject `istio-proxy`. The package does not set `sidecar.istio.io/inject` or `istio-injection=enabled`. The test task requires that label and rejects an `istio-proxy` or `istio-validation` container before the gateway checks.

No waypoint is configured. The Package service mesh field only selects `ambient` or `sidecar`. A waypoint is what Authservice adds, and Authservice is off. Ports 8443, 8446, and 8089 are passthrough TLS, including client certificates, so a waypoint must not terminate them. Port 8447 is TLS from the tenant gateway to the pod, carried inside the HBONE tunnel. ztunnel forwards that connection. The smoke and UI tasks then open all four routes.

The upstream database Job sets `proxy.istio.io/config`. UDS `RestrictIstioSidecarOverrides` denies that annotation. Exemption `takserver-db-setup` in `uds-policy-exemptions` allows only that policy for pods named `takserver-db-setup-*`. The cert Job does not set an Istio annotation. The OIDC init container is added to the existing TAK pods and does not set one either.

Inside the cluster, `sso.<domain>` resolves to the ClusterIP of `tenant-ingressgateway` in `istio-tenant-gateway` (see [In-cluster DNS](#in-cluster-dns)). The Istio 1.31 gateway chart labels those pods `app: tenant-ingressgateway` and `istio: tenant-ingressgateway`.

## In-cluster DNS

Public DNS for `*.uds.dev` answers `127.0.0.1`. From inside a pod that is the pod itself, so a pod cannot reach `sso.uds.dev` or `takserver.uds.dev` by name without help. uds-k3d ships ConfigMap `kube-system/coredns-custom` with key `uds.override`, which rewrites `*.admin.uds.dev` to the admin gateway and every other `*.uds.dev` name to the tenant gateway. It has no rule for passthrough hosts and only covers `uds.dev`.

The `takserver` component's first `onDeploy` action adds key `00-takserver.override` to that ConfigMap, built from the `DOMAIN` and `PASSTHROUGH_HOSTS` variables, and restarts CoreDNS when the key changed:

| Name | Answer |
| --- | --- |
| `takserver-api.<domain>`, `takserver-stream.<domain>` | `passthrough-ingressgateway.istio-passthrough-gateway` ClusterIP |
| `*.admin.<domain>` | `admin-ingressgateway.istio-admin-gateway` ClusterIP |
| any other `*.<domain>` (`sso`, `takserver`, `map`, ...) | `tenant-ingressgateway.istio-tenant-gateway` ClusterIP |

Each rule is a CoreDNS `rewrite stop` with `answer auto`, the same form uds-k3d uses. The k3s Corefile imports the `*.override` keys in name order, and the first matching `stop` rule wins, so these rules run before `uds.override`. A rule is written only when its gateway Service exists.

`takserver.<domain>` is on both gateways: the tenant gateway serves the browser UI on 443, and the passthrough gateway serves certificate enrollment (8446) by SNI. A name has one answer, so inside the cluster it resolves to the tenant gateway. In-cluster clients reach 8446 through `takserver-api-service`.

Pods in an ambient namespace can get a different, equally correct answer. The UDS operator writes a `MeshInternal` ServiceEntry for every exposed host, with the gateway Service as its endpoint. ztunnel's DNS proxy answers names that have a ServiceEntry before CoreDNS sees the query, with an address it allocates from `240.240.0.0/16`, and routes connections to that address to the ServiceEntry endpoint, the same gateway. Names without a ServiceEntry, and pods outside the mesh, get the CoreDNS answer. On a cluster without `coredns-custom` the ServiceEntries alone still steer ambient pods, as long as public DNS answers the name at all.

The action does nothing when `coredns-custom` does not exist, which is the case on a cluster with real DNS, or when `IN_CLUSTER_DNS` is not `true`. `uds run test:dns` checks the answers from inside the API pod and that the API Deployment has no `hostAliases`. It accepts the gateway ClusterIP, or a `240.240.0.0/16` address when the name's ServiceEntry points at the expected gateway Service. Earlier versions of this package gave the API pod a hostAlias for `sso.<domain>`. An upgrade removes it.
