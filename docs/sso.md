# Single sign-on

TAK Server 5.7 has its own OpenID Connect authorization-code flow. The Package registers one Keycloak client. An init container fills the client secret into `CoreConfig.xml` on every start. Authservice is not in front of TAK.

| Field | Value |
| --- | --- |
| Client id | `uds-takserver` |
| Protocol | `openid-connect` |
| Public client | false |
| Standard flow | true |
| Full scope | false |
| Default scopes | `openid`, `profile`, `email` |
| Refresh tokens | `use.refresh.tokens=true` |
| Login gate | `groups.anyOf` `/UDS Core/Admin` |
| Secret | `takserver-sso`, key `TAK_OIDC_CLIENT_SECRET` |
| Redirect | `https://takserver.<domain>/login/redirect` |
| Issuer document | `https://sso.<domain>/realms/uds/.well-known/openid-configuration` |
| Authservice | not used |

`GET /login/auth` redirects the browser to Keycloak. `GET /login/redirect` exchanges the code. `GET /login/refresh` refreshes the token (`com.bbn.marti.oauth.OAuthApi`). `useTakServerLoginPage` is false, so a 401 on the browser connector is sent to `/login/auth`.

The browser UI is `https://takserver.<domain>/` on the tenant gateway, which terminates TLS and forwards HTTP to port 8447. The redirect has no port because that host is published on 443. Certificate enrollment stays on 8446. Ports 8443 and 8089 still require a client certificate.

## Connectors

| Port | TLS | Client certificate | UI |
| --- | --- | --- | --- |
| 8443 | on | required | unchanged cert-only connector |
| 8446 | on, passthrough | off | admin UI and WebTAK off. Enrollment (`/Marti/api/tls/signClient/v2` with a bearer token) and `/login/.well-known/openid-configuration` |
| 8447 | off | off | admin UI, WebTAK, and the non-admin UI |
| 8089 | on | required | streaming, unchanged |

Bearer tokens and the access-token cookie are accepted only when the local port is 8446 or 8447 (`AccessTokenResolver`). The stock API Service does not publish 8447. This chart adds Service `takserver-web` with port name `http` so the tenant gateway does not speak TLS to the plaintext connector.

## CoreConfig

`auth` stays `default="file"`. `X509Authenticator` throws if the default is not a supported method, and `file` is the one certificate login still uses. `x509groups` and `x509tokenAuth` are on. There is one discovery entry and no `authServer`.

```xml
<auth default="file" x509groups="true" x509tokenAuth="true">
    <File location="/opt/tak/UserAuthenticationFile.xml"/>
    <oauth oauthUseGroupCache="false"
           useTakServerLoginPage="false"
           usernameClaim="preferred_username"
           groupsClaim="groups"
           groupprefix="/tak/"
           groupNameExtractorRegex="^/TAK/(.+)$"
           readGroupSuffix="_READ"
           writeGroupSuffix="_WRITE"
           adminTokenClaimName="groups"
           adminTokenClaimValue="/UDS Core/Admin">
        <openIdDiscoveryConfiguration name="UDS SSO"
            clientId="uds-takserver"
            secret="${TAK_OIDC_CLIENT_SECRET}"
            redirectUri="https://takserver.uds.dev/login/redirect"
            configurationUri="https://sso.uds.dev/realms/uds/.well-known/openid-configuration"
            trustAllCerts="false"/>
    </oauth>
</auth>
```

The upstream chart mounts `CoreConfig.xml` read-only and has no init-container value. After Helm, the package strategic-merges an init container onto the config, messaging, and API pods. That container runs `envsubst '${TAK_OIDC_CLIENT_SECRET}'` from Secret `takserver-sso` into `/conf/CoreConfig.xml`. TAK prefers `conf/CoreConfig.xml` over `CoreConfig.xml` (`LocalConfiguration`). The config service is what publishes the file to the other processes. The secret template is only `TAK_OIDC_CLIENT_SECRET: clientField(secret)`. The secret is labeled `uds.dev/pod-reload: "true"` with selector `uds.dev/oidc-reload=takserver`, so a rotated secret restarts those pods and the init container reads it again.

`trustAllCerts` is false. The API init container copies the JVM trust store and imports ConfigMap `uds-trust-bundle` when that file has certificates. Slim core does not set the CA bundle variables, and the operator deletes the ConfigMap when the bundle would be empty. The init then imports the certificate chain presented by the tenant gateway for the discovery host. `sso.<domain>` resolves to `127.0.0.1` in this dev DNS, including from inside a pod, where that address is the pod itself. The API pod gets a hostAlias to the tenant gateway ClusterIP. Public DNS for `sso.uds.dev` is also `127.0.0.1`.

## Groups

`OAuthAuthenticator` lowercases `groupprefix` and `LdapAuthenticator.applyGroupPrefixFilter` lowercases the claim before `startsWith`, then keeps the original string. Prefix `/tak/` therefore matches `/TAK/...`. `GroupNameExtractor` compiles the regex `CASE_INSENSITIVE`, so `^/TAK/(.+)$` does not need a lowercase pattern. Names that end in `_READ` or `_WRITE` set the direction and the suffix is removed, so `/TAK/Operators_READ` becomes TAK group `Operators` with direction OUT.

`/UDS Core/Admin` does not match `/tak/`. It is only the admin claim (`adminTokenClaimName` / `adminTokenClaimValue`), which grants `ROLE_ADMIN` before the prefix filter. The Package `groups.anyOf` list is a Keycloak login gate, not the TAK group map. The group-membership mapper puts full paths in the access token and the ID token. `claim.name` is `groups`. That mapper is already on the UDS default protocol-mapper allowlist, so `SECURITY_HARDENING_ADDITIONAL_PROTOCOL_MAPPERS` is left empty.

`usernameClaim` is `preferred_username`.

`/UDS Core/Admin` sends `HomeApi` to `/Marti`. The test user is also in `/TAK/Operators_READ`, and `GET /Marti/api/groups/all` is what shows that mapped group. There is no route named whoami.

## What TAK does not check

TAK verifies the RS256 signature and nothing else about the token:

- No issuer check. Discovery stores the signing key and clears `issuer`. Any token from the `uds` realm whose signature matches that key is accepted, including a token minted for a different client, as long as the group claims match.
- No audience check.
- No PKCE. The client does not set `pkce.code.challenge.method`.
- Logout clears the access-token cookie and redirects inside TAK (`AuthCookieUtils.logout`). It does not call the Keycloak end-session endpoint, so the Keycloak session stays logged in.
- One IdP. A second `openIdDiscoveryConfiguration` is not a failover list. TAK picks one entry at random.
- Port 8089 does not take a browser cookie. With `x509tokenAuth`, a certificate that was enrolled on 8446 with a bearer token is authenticated as that token's user.
- Cookies set on 8447 are not marked Secure. `AuthCookieUtils` uses `request.isSecure()`, and `tls="false"` makes that false even though the browser reached TAK through the tenant gateway's HTTPS listener.

## Why not Authservice

Authservice sits on the tenant gateway and authenticates the request before the application sees it. TAK's login is the authorization-code flow above: the browser must reach `/login/auth` and `/login/redirect`, and TAK must set its own access-token cookie. That cookie is only read on local ports 8446 and 8447. Authservice would replace that flow and would not produce the cookie TAK checks.

8443 and 8089 must keep presenting the client certificate to TAK. Passthrough does that. Putting Authservice on those hosts would terminate the connection first and TAK would not see the certificate. The browser UI is the only port moved to the tenant gateway, and it uses TAK's client rather than Authservice.

## Network

API pods may connect to the tenant gateway:

- Namespace `istio-tenant-gateway`
- Pod labels `app=tenant-ingressgateway` and `istio=tenant-ingressgateway` (Istio gateway chart 1.31, release name `tenant-ingressgateway`)
- Port 443

That is the path for the discovery document, the token endpoint, and JWKS. The calls use `https://sso.<domain>/...`. The hostAlias sends that name to the gateway ClusterIP. There is no rule to Keycloak's pod on port 8080, and there is no Kubernetes API rule for a render Job. The init container only reads the secret volume.

## Tests

`uds run test-install` calls `setup:keycloak-user` with `/UDS Core/Admin`, then `tests/ensure-tak-group.py` adds `/TAK/Operators_READ`. Playwright opens `https://takserver.uds.dev/` on the tenant gateway, expects the Keycloak page, signs in as `doug`, and lands on `/Marti/`. TAK has no route named whoami. The test reads `Operators` from `GET /Marti/api/groups/all` and `ROLE_ADMIN` from `GET /Marti/api/util/user/roles`. `GET /Marti/api/util/isAdmin` is true for that user.

Enrollment is `POST /Marti/api/tls/signClient/v2` on 8446 with the access-token cookie value as a bearer token and no client certificate. `CoreConfig` `certificateSigning` uses `certs/files/ca-signing.jks`, which the cert Job builds from the generated root CA. The CSR common name is the Keycloak username. `O` and `OU` are `TAK` and `UDS`.

The same spec, and `tests/smoke.sh`, check that 8443 and 8089 reject a handshake with no client certificate. The 8443 Marti check still uses `admin.pem`. If `https://sso.<domain>` does not answer, the job skips the account-console setup and the OAuth spec and still runs the certificate checks.

`tests/api-smoke.sh` is the API smoke test. `test:all` runs it after install and after upgrade. On 8443 it calls version, groups, contacts, and a mission create, read, and delete with the admin certificate, and the same calls with no certificate must fail. On 8447 it signs in as `doug` through the authorization-code flow (no extra Keycloak client), then calls version, roles, isAdmin, and groups. `GET /Marti/api/whoami` is requested too. TAK 5.7 returns 404 for that path, so the user and mapped group are `ROLE_ADMIN` and `Operators`. A missing token must be 401 or a redirect. A token with a damaged signature must be 401. On 8446 the bearer token enrolls a certificate and the OIDC document must name the Keycloak endpoints. On 8089 that certificate must complete TLS, and a client with no certificate must be rejected.
