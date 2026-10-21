# 4. TAK OAuth uses one OpenID discovery entry on port 8447

Date: 2026-10-18

## Status

Accepted. The 8447 connector is TLS since [ADR 0006](0006-re-encrypt-gateway-traffic-to-tak.md).

## Context

TAK Server 5.7-RELEASE-14 implements an authorization-code flow on `/login/auth`, `/login/redirect`, and `/login/refresh`. Bearer tokens and the access-token cookie are accepted only on local ports 8446 and 8447. `auth default` has to stay `file`, because `X509Authenticator` rejects any other default. `authServer.issuer` is a `.pem`, `.der`, or `.crt` path when no key children are set, not an issuer URL. More than one `openIdDiscoveryConfiguration` is not a list TAK fails over: it picks one at random. Signature checks are RS256 only. There is no issuer check, no audience check, and no PKCE.

The stock Helm chart has no init-container value and its API Service has no port 8447. The browser has to reach a connector that does not require a client certificate, without moving 8443 or 8089 off client certificates. Authservice terminates HTTP on the tenant gateway and would replace TAK's login instead of letting TAK set the cookie it later reads.

## Decision

Keep the upstream chart. Inject connectors and the auth block through the `core-config` ConfigMap this package already mounts.

- 8443 stays certificate-only.
- 8446 stays TLS passthrough with `clientAuth="false"`, `enableAdminUI="false"`, and `enableWebtak="false"`. It remains the enrollment port and the port that serves `/login/.well-known/openid-configuration`.
- 8447 is a new `tls="false"` `clientAuth="false"` connector with the admin UI, WebTAK, and the non-admin UI enabled. Service `takserver-web` publishes it. The tenant gateway exposes host `takserver` to that port. Passthrough still exposes 8443, 8446, and 8089.
- `auth` is `default="file"` with `x509groups="true"` and `x509tokenAuth="true"`, then one `openIdDiscoveryConfiguration` named `UDS SSO`. There is no `authServer` element.
- The client secret is `${TAK_OIDC_CLIENT_SECRET}`. An init container runs `envsubst` from Secret `takserver-sso` into `/conf/CoreConfig.xml`, which TAK prefers over the mounted file. The `takserver-oidc` Pepr module adds the init container to each TAK pod at admission because the chart cannot express it, so no pod starts with the unrendered file. The secret carries the pod-reload label so a rotation restarts those pods.
- `groupprefix` stays `/tak/` and the extractor stays `^/TAK/(.+)$`. TAK lowercases the prefix and the claim before the prefix compare, and compiles the regex case-insensitively, so those two strings already match `/TAK/...`.
- `trustAllCerts` is false. The API and messaging pods trust the UDS bundle and reaches `sso.<domain>` at the tenant gateway through the in-cluster DNS rewrite (see docs/networking.md). The first version used a hostAlias on the API pod.

`/UDS Core/Admin` in the `groups` claim is `ROLE_ADMIN`. Groups under `/TAK/` with `_READ` or `_WRITE` are the TAK groups. The Keycloak client uses the standard group-membership mapper, which the UDS hardening policy already allows.

The Package keeps `spec.network.serviceMesh.mode: ambient`. That is the UDS Core mesh mode. It enrolls the namespace with `istio.io/dataplane-mode=ambient` and does not add a sidecar. This package sets no `sidecar.istio.io/inject` label or annotation, and it does not label the namespace `istio-injection=enabled`. The OIDC init container is a normal init container on the TAK pods.

A waypoint is not added. On this Package CR the service mesh object only has `mode`. The waypoint UDS can create belongs to an Authservice client, and Authservice stays off. Passthrough to 8443, 8446, and 8089 is TLS that TAK has to terminate, including the client certificate on 8443 and 8089. A waypoint in front of those ports would end that TLS. The tenant gateway already terminates TLS for 8447 and forwards HTTP. ztunnel delivers that TCP connection to the pod without a waypoint. The mesh test requires the namespace label and zero `istio-proxy` containers, then the gateway tests open 8447, 8446, 8443, and 8089.

The upstream database Job still sets `proxy.istio.io/config`. The chart has no value that removes it. Exemption `takserver-db-setup` admits that Job. Ambient mode does not turn the annotation into a sidecar.

## Consequences

Any `uds` realm token whose RS256 signature matches the realm key and whose groups match is accepted, including a token that was minted for a different client. Logout does not end the Keycloak session. There is one IdP. Port 8089 uses certificates that were bound to a token during enrollment on 8446. Cookies on 8447 are not marked Secure, because the connector is plaintext behind the gateway and TAK only sets Secure when `request.isSecure()` is true. See [Single sign-on](../docs/sso.md).
