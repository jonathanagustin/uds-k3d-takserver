# Networking

This page describes how traffic reaches TAK Server, which flows the package allows, how the mesh is set up, and how names resolve inside the cluster.

The UDS operator turns the Package `network` block into NetworkPolicy and Istio resources. The rules are in `charts/takserver/templates/uds-package.yaml`. This package ships its own Istio objects only for the DestinationRule described in [Tenant gateway to 8447](#tenant-gateway-to-8447) and for the [standard TAK ports](#standard-tak-ports).

## Exposure

The upstream chart's nginx ingress stays off. The Package exposes the same three ports (8446, 8443, and 8089) on the passthrough gateway, and the browser UI on the tenant gateway. Passthrough forwards raw TLS. Istio does not terminate it.

| Host | Gateway | Service | Port | Why this port |
| --- | --- | --- | --- | --- |
| `takserver.<domain>` | tenant | `takserver-web` | 8447 | Browser UI. The gateway ends browser TLS and opens a new TLS connection to the pod. `clientAuth` off, admin UI and WebTAK on. |
| `takserver.<domain>` | passthrough | `takserver-api-service` | 8446 | Certificate enrollment and the OIDC discovery document. Admin UI and WebTAK are off. |
| `takserver-api.<domain>` | passthrough | `takserver-api-service` | 8443 | Upstream `tak-api-cert`. The connector requires a client certificate. |
| `takserver-stream.<domain>` | passthrough | `takserver-messaging-service` | 8089 | Upstream streaming ingress. ATAK usually dials 8089. Here that listener is SNI on the passthrough gateway. |

Ports 8444, 9000, and 9001 stay on the Services and have no gateway host. TLS on 8089, 8443, 8444, 8446, 9000, and 9001 is not terminated by the tenant gateway.

Messaging also binds plaintext 8080, and the actuator is on that port. No Service in this package publishes 8080, and AuthorizationPolicy `takserver-deny-plaintext-8080` denies it to messaging, the API, and Ignite.

API and messaging also listen on plaintext 9100 for Prometheus (the JMX exporter javaagent). That port is not published. The Package monitor is what lets Prometheus scrape it.

`k3d-core-slim-dev` does not select `istio-passthrough-gateway`. `bundle/uds-bundle.yaml` turns that optional component on for tests.

On k3d, host port 443 is the tenant gateway. Tests port-forward `svc/passthrough-ingressgateway` in `istio-passthrough-gateway` and send SNI to that local port.

### Uptime probes and Portal tiles

The Package `expose` entries also tell UDS Core what to monitor and what to show in UDS Portal:

| Expose entry | Portal tile | Uptime check |
| --- | --- | --- |
| `tak-web-http` (`takserver.<domain>`, tenant), only when `sso.enabled` | "TAK Server" (`uds.dev/title`) | `/login`. TAK serves its own login page there with status 200 and no redirect |
| `tak-api-https`, `tak-api-cert`, `tak-messaging-streaming` (passthrough) | none (`uds.dev/visible: "false"`) | none directly. `tak-health` checks them. See [Client-port health](#client-port-health) |
| `tak-health` (`tak-health.admin.<domain>`, admin), only when `health.enabled` | none (`uds.dev/visible: "false"`) | `/stream`, `/api`, and `/enroll`. Each answers 200 when its TAK port passed its last check |
| `cloudtak-map` (`map.<domain>`, tenant) | "CloudTAK" (`uds.dev/title`) | `/login`, which answers 200 without a session |
| ATAK viewer (`atak.<domain>`, tenant, optional package) | no `uds.dev/title` set | `/phone.html`, through Authservice. The full-core job does not deploy this package, so it does not check this probe. See [ATAK test device](atak-device.md) |

The package metadata that Portal and the package catalog read (title, tagline, categories, keywords, and icon) is in the `metadata.annotations` block of `zarf.yaml`. The icon is the base64 of `assets/icon.svg`, and hk's `icon` check fails when they differ.

### Uptime monitoring

The package uses UDS Core [uptime monitoring](https://docs.defenseunicorns.com/core/how-to-guides/monitoring--observability/set-up-uptime-monitoring/). Each check is an `uptime.checks.paths` entry on an `expose` entry. The UDS operator turns it into a Prometheus Probe in the package's namespace, and Blackbox Exporter sends an HTTPS GET to `https://<host>.<domain><path>` at a regular interval. A check passes on a 2xx answer.

| Probe | Namespace | Target |
| --- | --- | --- |
| `uds-takserver-tenant-uptime` | `takserver` | `https://takserver.<domain>/login` |
| `uds-tak-health-admin-uptime` | `takserver` | `https://tak-health.admin.<domain>/stream`, `/api`, and `/enroll` |
| `uds-map-tenant-uptime` | `cloudtak` | `https://map.<domain>/login` |
| `uds-atak-tenant-uptime` (optional package) | `atak` | `https://atak.<domain>/phone.html` |

Why `/login` for TAK: the default Blackbox module follows redirects, so a check on a path that redirects passes on whatever page the redirect ends on. TAK redirects a signed-out request for `/` once before a page answers. TAK serves `/login` itself with 200 and no redirect, so a pass means TAK answered. UDS Core probes Grafana on `/healthz` for the same reason: its other paths redirect to Keycloak.

The ATAK viewer is behind Authservice. For that probe the UDS operator creates Keycloak client `uds-atak-viewer-probe` and signs the probe in with it. No other setup is needed.

To turn a check off, set `uptime.enabled: false` on chart `uds-takserver-config` (component `takserver`) or chart `uds-cloudtak` (component `cloudtak`). UDS Core uses the same switch for Keycloak and Grafana. In a bundle:

```yaml
packages:
  - name: takserver
    overrides:
      takserver:
        uds-takserver-config:
          values:
            - path: uptime.enabled
              value: false
      cloudtak:
        uds-cloudtak:
          values:
            - path: uptime.enabled
              value: false
```

#### Where to see the results

- Grafana dashboard **UDS / Monitoring / Probe Uptime** shows each target's status over time, its uptime percentage, and when its TLS certificate expires.
- In Grafana Explore, query `probe_success{instance="https://takserver.<domain>/login"}`. 1 is up and 0 is down.
- `uds zarf tools kubectl get package -n takserver` lists the probe names in the Probes column.

UDS Core ships three alerts for every probe, ours included:

| Alert | Fires when |
| --- | --- |
| `UDSProbeEndpointDown` | the check has failed for 5 minutes |
| `UDSProbeTLSExpiryWarning` | the certificate expires in less than 30 days |
| `UDSProbeTLSExpiryCritical` | the certificate expires in less than 14 days |

The thresholds are UDS Core settings under `udsCoreDefaultAlerts` in the `uds-prometheus-config` chart. See [Monitoring and observability](https://docs.defenseunicorns.com/core/reference/configuration/monitoring-and-observability/).

#### Client-port health

UDS Core cannot probe TAK's client ports itself. Its probe only sends an HTTPS GET and must trust the server certificate. On the passthrough hosts TAK serves the package's own CA, not the gateway certificate. Ports 8443 and 8089 also require a client certificate, and 8089 is not HTTP. The UDS Core API has no field for a custom probe module, and the operator overwrites the Blackbox configuration Secret.

The `tak-health` pod fills that gap. Every 30 seconds it connects to TAK the way a TAK client does, through the passthrough gateway:

| Path | TAK port | Passes when |
| --- | --- | --- |
| `/stream` | 8089 (`takserver-stream.<domain>`) | the mutual TLS handshake succeeds and TAK answers a CoT ping (`t-x-c-t`) with a pong (`t-x-c-t-r`) |
| `/api` | 8443 (`takserver-api.<domain>` on 443) | the mutual TLS handshake succeeds and `GET /Marti/api/version` returns 200 |
| `/enroll` | 8446 (`takserver-stream.<domain>`) | the TLS handshake succeeds and `GET /login` returns 200. No client certificate |

Each path answers 200 when its last check passed and is at most 90 seconds old, about three check intervals. Otherwise it answers 503. So a stopped check loop also shows as down. The `tak-health` expose entry lists the three paths under `uptime.checks.paths` on the admin gateway. UDS Core probes them, and its alerts and **Probe Uptime** dashboard include them with no extra setup. The entry does not depend on `sso.enabled`, so TAK without SSO is checked too.

**Client certificate.** The cert-init Job issues the pod its own client certificate, `CN=tak-health`, signed by the deploy-time CA. It stores it in Secret `tak-health-client` as `ca.pem`, `client.pem`, and `client.key`. The certificate:

- is for client authentication only, and is valid for 730 days;
- is not in TAK's user file, so it has no TAK groups and no admin role;
- has an unencrypted key, so the pod does not read the keystore password.

The pod mounts only that Secret, read-only, and runs as a non-root user with no Linux capabilities. Anyone who can read Secrets in the `takserver` namespace can read the key. That is the same group that can already read `takserver-certs`. The Job issues a new certificate on install or upgrade when the Secret is missing, was signed by another CA, or expires within 30 days. Each check reads the files again, so the pod uses a new certificate once the kubelet updates the mounted Secret, without a restart. UDS Core's TLS expiry alerts watch the admin gateway certificate, not this one.

**Network.** The pod may connect only to the passthrough gateway on ports 443, 8446, and 8089. Its HTTP answers carry only a pass or fail and a short reason, never certificate material.

**What the certificate can and cannot do.** TAK accepts it on 8089 and 8443 because the deploy-time CA signed it. The `auth` block in `CoreConfig.xml` sets `x509groups="true"` and leaves `x509addAnonymous` at its default, `false`, so the certificate gets no groups. With no groups it receives no CoT from other clients, and data that TAK limits by group, such as missions and files, is not visible to it. It has no admin role, so admin pages and admin API calls are refused. It can still open a connection and call API endpoints that TAK does not limit by group, such as `/Marti/api/version`. The package does not set up certificate revocation checks in TAK, so to stop the certificate working before it expires, rotate the deploy-time CA.

**With the TAK alerts.** These checks are in addition to the alerts in PrometheusRule `takserver` (see [Monitoring](configuration.md#monitoring)), not a replacement. Those alerts read the JMX exporter and kube-state-metrics: a Deployment scaled to 0, no available pods, a high JVM heap, or a restart loop. They do not show whether a client can connect. `tak-health` checks that. It does not see heap use or restarts.

**Turn it off.** Set the package value `health.enabled` to `false`:

```bash
uds zarf package deploy <package> --set-values health.enabled=false
```

In a bundle, set `health.enabled: false` on chart `uds-takserver-config` the same way as `uptime.enabled` above. The chart then renders no `tak-health` pod, Service, expose entry, or certificate. A Secret `tak-health-client` from an earlier install stays until you delete it.

#### What has no uptime check

- With `health.enabled` set to `false`: the passthrough hosts, for the reasons in [Client-port health](#client-port-health). With `sso.enabled` also `false`, TAK has no uptime check at all, because the chart does not create the `takserver-web` Service or the tenant `expose` entry.

#### When a check fails

1. Find the failing target: `probe_success == 0` in Grafana Explore, or the `instance` label on the alert.
2. Check the HTTP status: `probe_http_status_code` for the same `instance`. 0 means no connection. 503 usually means the gateway has no ready pod behind it.
3. Check the workload: `uds zarf tools kubectl get pods -n takserver` (or `-n cloudtak`). For TAK, the `takserver-api` pod serves `/login`.
4. For a `tak-health` target, read the pod's last checks: `uds zarf tools kubectl logs deploy/tak-health -n takserver --tail=6`. A line like `check stream ok=0 ...` gives the reason. `/stream` depends on `takserver-messaging`, and `/api` and `/enroll` on `takserver-api`.
5. Check the probe exists: `uds zarf tools kubectl get probes.monitoring.coreos.com -A`. If it is missing, run `uds zarf tools kubectl describe package -n takserver` and read the status.
6. For the ATAK viewer, check the UDS operator logs for the `uds-atak-viewer-probe` client.

#### How CI tests it

Slim core installs neither the Probe API nor Portal. The full-core job checks both. `tests/uptime-probes.sh` lists the TAK and CloudTAK probes. It requires `probe_success` 1 for both. For TAK it also requires status 200 with no redirect, so a redirect to Keycloak cannot pass in TAK's place. Then it scales CloudTAK to zero and back, and records the drop and the recovery. It then requires `probe_success` 1 for the three `tak-health` paths, scales `takserver-messaging` to zero, requires `/stream` to drop to 0, and logs the `/api` and `/enroll` results at that point. It scales messaging back and requires `/stream` to return to 1. It skips when the Probe CRD is absent. `tests/portal.sh` runs `tests/portal.spec.ts`, which signs in as an admin and expects exactly the "CloudTAK" and "TAK Server" tiles besides My Account, then signs in as `mapuser` (in `/CloudTAK/Users`, not an admin) and expects only "CloudTAK", then signs in as a user in neither group and expects neither tile.

### Standard TAK ports

A field client such as ATAK enrolls at `<host>:8446` and then streams to the same `<host>:8089`, with the port taken from its settings and the host shared. The 443 routes above give each port its own host, so a client cannot use them with one server entry.

`charts/takserver/templates/standard-ports.yaml` adds an Istio Gateway on the passthrough gateway pods. The gateway has a TLS passthrough listener on 8446 and a TCP listener on 8089. A VirtualService sends 8446 to `takserver-api-service:8446`. That route matches on port and on SNI. The SNI hosts are `standardPorts.hosts`, which defaults to `takserver` and `takserver-stream`.

The same VirtualService sends 8089 to `takserver-messaging-service:8089` and matches on port alone. ATAK's streaming library does not send SNI, so an SNI match on 8089 would drop it. TLS still runs end to end on 8089 and TAK still requires the client certificate. The 443 routes stay as they are.

See [ADR 0012](../adr/0012-standard-tak-ports-on-the-passthrough-gateway.md). The gateway Service publishes the two ports through the bundle override `istio-passthrough-gateway.gateway` `service.ports` in `bundle/uds-bundle.yaml`. The Istio gateway chart's NetworkPolicy opens every port in that list. Traffic to TAK uses the same Service ports as the Package expose entries, so the operator's ingress rules for 8446 and 8089 already cover it and no rule is added. Set `standardPorts.enabled: false` to drop the listeners. Without the Service ports they are inert.

Inside the cluster, `takserver.<domain>` resolves to the tenant gateway (see [In-cluster DNS](#in-cluster-dns)), so in-cluster clients use `takserver-stream.<domain>:8446` and `:8089`. Outside the cluster, point the TAK host at the passthrough gateway's load balancer. On k3d, host ports 8446 and 8089 are not mapped. Tests port-forward them.

`uds run test:gateway` writes `/tmp/tak-std-ports`. `tests/api-smoke.sh` enrolls a certificate on 8446, streams a CoT event on 8089 with it, and waits for the client in `/Marti/api/clientEndPoints` as seen by that user. That list only shows clients that share a group with the caller, and the admin certificate has none.

### QUIC

QUIC is off by default: `quic.enabled` is `false`. With it off, the chart adds no QUIC input, no UDP Service, and no UDP expose entry.

When `quic.enabled` is `true`, the chart does three things:

- CoreConfig gets `<input _name="quic" protocol="quic" port="8090" coreVersion="2"/>`.
- Service `takserver-messaging-quic` publishes UDP 8090 to the messaging pods.
- The Package exposes that Service with `protocol: UDP` and no host.

UDS Core sends that UDP traffic through Envoy Gateway, not Istio. The UDS operator writes the route and one NetworkPolicy. That policy lets only the Envoy default gateway proxy reach the messaging pods on UDP 8090. Istio AuthorizationPolicy and mesh mTLS do not cover this path.

TAK itself requires a client certificate. In TAK 5.7-RELEASE-14 the QUIC TLS context uses `ClientAuth.REQUIRE`, and the input's `auth` defaults to `x509`, the same as 8089. The anonymous UDP input on 8087 and the multicast inputs are not added.

The messaging image ships the Netty QUIC native library for both linux-x86_64 and linux-aarch_64, so QUIC works on amd64 and arm64 nodes.

The test bundle selects `envoy-gateway` and `envoy-default-gateway` and sets `quic.enabled`. Other bundles leave all three off. `tests/quic.sh` then checks two things through the gateway's UDP 8090 on both amd64 and arm64:

- A client with no certificate must be refused with a TLS alert. No answer at all fails the test, so a broken route cannot pass as a refusal.
- A client with the admin certificate must stream a CoT event, and its uid must appear in `/Marti/api/subscriptions/all`. TAK can take about 30 seconds to add a new stream to that list, so the script waits up to about 90 seconds. If the uid still is not listed, the client reconnects once before the test fails, like the port 8089 check in `tests/api-smoke.sh`.

The script exits early when the QUIC Service is missing, unless Envoy Gateway is installed, because then the flag did not reach the chart. See [ADR 20](../adr/0020-quic-through-envoy-gateway.md).

## Tenant gateway to 8447

The Package CR `expose` entry cannot ask the gateway to use TLS toward the Service. The chart adds that part as plain Istio, outside the Package CR, when `api.web.backendTLS.enabled` is `true` (the default):

- The 8447 connector serves TLS from `certs/files/takserver-web.jks`. The cert Job issues it from the deploy-time CA, with the names `takserver-web`, `takserver-web.takserver`, `takserver-web.takserver.svc`, and `takserver-web.takserver.svc.cluster.local`.
- Service `takserver-web` port is `https` with `appProtocol: https`.
- DestinationRule `takserver-web` sets TLS mode `SIMPLE` on port 8447 with SNI `takserver-web.takserver.svc.cluster.local`, the same expected name, and `credentialName: takserver-web-ca`. It is exported only to `istio-tenant-gateway`. `insecureSkipVerify` is not set.
- A Zarf deploy action copies `ca.pem` from ConfigMap `cert-migration` into Secret `takserver-web-ca` (key `cacert`) in `istio-tenant-gateway`. A gateway reads `credentialName` only from its own namespace. The CA key is not copied.

In ambient mode the gateway's TLS connection still travels inside HBONE (Istio's HTTP-based tunnel between workloads), so strict mutual TLS (mTLS) still applies. TAK then reports no non-secure ports and marks its cookies Secure. The trade-offs are in [ADR 0006](../adr/0006-re-encrypt-gateway-traffic-to-tak.md).

## Allow rules

The package allows only the flows below. Every allow rule has its own description. Pepr names the NetworkPolicy from that description, so two rules that share a description collide.

| Direction | Scope | Description |
| --- | --- | --- |
| Egress and Ingress | API, messaging, plugins, and the `takserver-db-setup` Job to Postgres, port 5432 | `Egress 5432 from <client> to postgres`, `Ingress 5432 to postgres from <client>` |
| Egress and Ingress | API, messaging, and plugins to NATS, port 4222 | `Egress 4222 from <client> to nats`, `Ingress 4222 to nats from <client>` |
| Egress and Ingress | Ignite to Ignite, ports 47100 and 47500 | `Egress <port> from takserver-ignite to ignite-peers`, and the Ingress rule |
| Egress and Ingress | every pair of API, messaging, config, and plugins, port 47100 | `Egress 47100 from <a> to <b>`, `Ingress 47100 to <b> from <a>` |
| Egress | `remoteGenerated: KubeAPI`, one rule per pod label in `kubeApi.selectors` | Ignite Kubernetes discovery for that label |
| Egress | namespace `istio-tenant-gateway`, labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway`, port 443, API selector, only when `sso.enabled` | Keycloak discovery, token, and JWKS |
| Egress | namespace `istio-tenant-gateway`, labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway`, port 443, messaging selector, only when `sso.enabled` | Keycloak discovery and JWKS for 8089 clients |
| Ingress | namespace `envoy-default-gateway`, the Envoy proxy labels, UDP 8090, messaging selector, only when `quic.enabled`. The UDS operator writes it from the UDP expose entry | QUIC from the Envoy default gateway |

Postgres, NATS, and Ignite are installed in the `takserver` namespace by the upstream chart. There is no namespace-wide allow rule. Each pod-to-pod flow is its own rule pair, from `intraNamespace` in `charts/takserver/values.yaml`: an Egress rule on the client and an Ingress rule on the server, both limited to the port.

The list comes from `tests/flows.py`, which reads `/proc/net/tcp` in every pod and maps each connection to a client pod, a server pod, and a port. Task `test:flows` runs it after the other tests and fails when a connection has no rule. The config pod holds no Postgres or NATS connection, so it is not a client of either. See [ADR 0007](../adr/0007-per-workload-network-rules.md).

Ignite also has explicit rules both ways between `takserver-ignite` and the API, messaging, config, and plugins pods on 47100, 47500, and 10800. A missing return path stalls until `igniteConnectionTimeoutSeconds` (300) before the client falls back.

Keycloak is not in the namespace. The API and messaging selectors' only external allow is port 443 on the tenant gateway, which fronts discovery, the token endpoint, and JWKS. Messaging needs it because a certificate enrolled with a Keycloak token is checked against the issuer again when the client connects on 8089 (`X509Authenticator` calls the OAuth authenticator). Without it the TLS handshake completes and TAK then drops the client.

There is no `remoteGenerated: Anywhere` rule and no Prometheus scrape rule. TAK does not expose a Prometheus endpoint, so nothing is opened for a scraper. See [ADR 0003](../adr/0003-no-prometheus-monitor.md).

The Ignite chart and the API, messaging, config, and plugins Deployments use ServiceAccount `takserver-ignite`. Each of those pod labels needs its own Kubernetes API rule. One rule limited to `app: takserver-ignite` drops the clients' API calls during the TLS handshake.

`additionalNetworkAllow` appends deployer rules. Each entry needs a unique `description`.

## Mesh

`network.serviceMesh.mode` is `ambient`. The operator labels namespace `takserver` with `istio.io/dataplane-mode=ambient` and does not inject `istio-proxy`. The package does not set `sidecar.istio.io/inject` or `istio-injection=enabled`. The test task requires that label and rejects an `istio-proxy` or `istio-validation` container before the gateway checks.

No waypoint is configured. The Package service mesh field only selects `ambient` or `sidecar`. A waypoint is what Authservice adds, and Authservice is off. Ports 8443, 8446, and 8089 are passthrough TLS, including client certificates, so a waypoint must not terminate them. Port 8447 is TLS from the tenant gateway to the pod, carried inside the HBONE tunnel. ztunnel, the ambient node proxy, forwards that connection. The smoke and UI tasks then open all four routes.

The upstream database Job sets `proxy.istio.io/config`. UDS `RestrictIstioSidecarOverrides` denies that annotation. Exemption `takserver-db-setup` in `uds-policy-exemptions` allows only that policy for pods named `takserver-db-setup-*`. The cert Job does not set an Istio annotation. The OIDC init container is added to the existing TAK pods and does not set one either.

Inside the cluster, `sso.<domain>` resolves to the ClusterIP of `tenant-ingressgateway` in `istio-tenant-gateway` (see [In-cluster DNS](#in-cluster-dns)). The Istio 1.31 gateway chart labels those pods `app: tenant-ingressgateway` and `istio: tenant-ingressgateway`.

## In-cluster DNS

Public DNS for `*.uds.dev` answers `127.0.0.1`. From inside a pod that is the pod itself, so a pod cannot reach `sso.uds.dev` or `takserver.uds.dev` by name without help. uds-k3d ships ConfigMap `kube-system/coredns-custom` with key `uds.override`, which rewrites `*.admin.uds.dev` to the admin gateway and every other `*.uds.dev` name to the tenant gateway. It has no rule for passthrough hosts and only covers `uds.dev`.

The `takserver-oidc` watcher writes key `00-takserver.override` on that ConfigMap, built from the `DOMAIN` and `PASSTHROUGH_HOSTS` variables, restarts CoreDNS when the key changed, and waits until that Deployment is Available:

| Name | Answer |
| --- | --- |
| `takserver-api.<domain>`, `takserver-stream.<domain>` | `passthrough-ingressgateway.istio-passthrough-gateway` ClusterIP |
| `*.admin.<domain>` | `admin-ingressgateway.istio-admin-gateway` ClusterIP |
| any other `*.<domain>` (`sso`, `takserver`, `map`, ...) | `tenant-ingressgateway.istio-tenant-gateway` ClusterIP |

Each rule is a CoreDNS `rewrite stop` with `answer auto`, the same form uds-k3d uses.

The k3s Corefile imports the `*.override` keys in name order, and the first matching `stop` rule wins, so these rules run before `uds.override`. A rule is written only when its gateway Service exists.

`takserver.<domain>` is on both gateways: the tenant gateway serves the browser UI on 443, and the passthrough gateway serves certificate enrollment (8446) by SNI. A name has one answer, so inside the cluster it resolves to the tenant gateway. In-cluster clients reach 8446 through `takserver-api-service`.

Pods in an ambient namespace can get a different, equally correct answer. The UDS operator writes a `MeshInternal` ServiceEntry for every exposed host, with the gateway Service as its endpoint. ztunnel's DNS proxy answers names that have a ServiceEntry before CoreDNS sees the query. It allocates an address from `240.240.0.0/16` and routes connections to that address to the ServiceEntry endpoint, the same gateway. Names without a ServiceEntry, and pods outside the mesh, get the CoreDNS answer. On a cluster without `coredns-custom` the ServiceEntries alone still steer ambient pods, as long as public DNS answers the name at all.

The reconcile does nothing when `coredns-custom` does not exist, which is the case on a cluster with real DNS, or when `IN_CLUSTER_DNS` is not `true`.

`uds run test:dns` checks the answers from inside the API pod and that the API Deployment has no `hostAliases`. It accepts the gateway ClusterIP, or a `240.240.0.0/16` address when the name's ServiceEntry points at the expected gateway Service. Earlier versions of this package gave the API pod a hostAlias for `sso.<domain>`. An upgrade removes it.
