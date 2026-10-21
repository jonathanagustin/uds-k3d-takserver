# CloudTAK

[CloudTAK](https://github.com/dfpc-coe/CloudTAK) is a browser map client for TAK Server. The optional `cloudtak` component runs it at `https://map.<domain>/`, next to the TAK web UI, and connects it to the TAK Server in the `takserver` namespace. The TAK Server deployment does not change, apart from three Ingress rules in its `Package` CR.

## What is deployed

| Object | Namespace | Purpose |
| --- | --- | --- |
| Deployment `cloudtak` | `cloudtak` | CloudTAK's nginx and API process on port 5000, plus the `sso` and `bootstrap` containers |
| StatefulSet `cloudtak-postgis` | `cloudtak` | CloudTAK's own PostGIS database, `postgis/postgis:15-3.4`, 2Gi volume |
| Secret `cloudtak` | `cloudtak` | Session signing secret, database password, and the password of the TAK account behind the admin connection. Generated on first install and kept on upgrade |
| Secret `cloudtak-sso` | `cloudtak` | Keycloak client secret, key `OIDC_CLIENT_SECRET`. Written by the UDS operator |
| Secret `cloudtak-tak-admin` | `cloudtak` | `ca.pem`, `admin.pem`, and `admin.key`, copied from ConfigMap `takserver/cert-migration` by the component's `onDeploy` action |
| Package `cloudtak` | `cloudtak` | Keycloak client `uds-cloudtak`, the `map` host on the tenant gateway, and the allow list |

Upstream CloudTAK's compose file also runs a tile server, an events worker, a media server, a retention job, and an S3 store. None of those are deployed. Without S3, CloudTAK features that store files (imports, attachments, uploaded basemaps, data packages) do not work. The map, CoT from TAK, and the admin pages do.

## Image

The image is built from the `upstream/cloudtak` git submodule, pinned to tag `v13.111.3` (`2b706cee75428788edcf010ec6bf2b5433f29a83`), and published as `ghcr.io/jonathanagustin/uds-k3d-takserver/cloudtak:v13.111.3`. No upstream image is used.

[`.github/container-and-chart/cloudtak/`](../.github/container-and-chart/cloudtak/) holds the build:

- `docker-bake.hcl` builds CloudTAK's own `Dockerfile` from the submodule with no changes. Its first stage downloads the CloudTAK-Data `v1.2.0` release zip, which upstream pins in that file.
- `Dockerfile` copies the built API (with `npm prune --omit=dev`) and the built web app onto the same `nginx:alpine3.24` base with `nodejs-current`, `bash`, and `openssl`. The upstream image is about 2.2 GB because it keeps its compilers and build dependencies. This one is about 600 MB.
- `start.sh` replaces upstream `api/start`. It renders the same `nginx.conf`, drops the `user` directive, and moves the pid file, logs, and temp paths under `/tmp`. The container runs as uid 101 with a read-only root filesystem.
- `sso.mjs` is the `sso` container's Keycloak sign-in. `nginx-sso.conf` and `nginx-sso-head.conf` are the two nginx fragments `start.sh` adds for it. See [Sign-in](#sign-in).
- `bootstrap.mjs` is the bootstrap container's script. See below.

`build.sh` refuses to build if the submodule is not at the pinned commit. The Test workflow's `images` job runs `build.sh --if-changed`, which builds and pushes only when the published image's `dev.uds-k3d-takserver.inputs` label differs from the submodule commit plus the git tree of that directory. `.github/workflows/cloudtak-image.yaml` does the same on `main`.

Renovate's `git-submodules` manager follows CloudTAK release tags. The tag strings marked `# cloudtak-version` in `zarf.yaml`, `cloudtak/chart/`, and `docker-bake.hcl` move in the same pull request.

## Sign-in

People sign in to CloudTAK through UDS Core Keycloak, on the same UDS login page as the TAK web UI. CloudTAK's own password and passkey sign-in is off.

1. `https://map.<domain>/` loads the CloudTAK app. With no session, the app routes to `/login`. nginx adds `/api/login/oidc/auto.js` to the app's HTML pages, and that script sends `/login` straight on to `/api/login/oidc`.
2. `/api/login/oidc` starts an authorization code flow with PKCE (S256) for Keycloak client `uds-cloudtak` in realm `uds`, and the browser lands on `https://sso.<domain>/realms/uds/protocol/openid-connect/auth`. The client allows members of `/UDS Core/Admin`, the same gate as the TAK client.
3. Keycloak returns to `https://map.<domain>/api/login/oidc/callback`. The `sso` container exchanges the code at Keycloak's token endpoint, in the cluster. `sso.<domain>` resolves to the tenant gateway through the in-cluster CoreDNS rewrite (see [Networking](networking.md)), and the Keycloak certificate is checked against the system trust store.
4. It enrols a TAK client certificate for the user on TAK's 8447 with the Keycloak access token as a bearer token, through the same TAK library call CloudTAK uses for password sign-in. TAK takes the username from `preferred_username` and the groups from `groups`, as it does for the TAK web UI (see [Single sign-on](sso.md)), so the certificate is the Keycloak user's own TAK identity with that user's TAK groups.
5. It creates or updates the CloudTAK profile for that username with the certificate, and opens a CloudTAK login session with CloudTAK's own session code. Members of `sso.adminGroup` (default `/UDS Core/Admin`) become CloudTAK system administrators.
6. The browser gets the session (login token, refresh token, session id) in the URL fragment of `/api/login/oidc/finish`, which is not sent to any server or written to a log. That page stores them where CloudTAK's own login page does and opens the map. The app restores the session, rotates the refresh token, and opens its own streaming connection to TAK's 8089 with the user's certificate.

### What CloudTAK does and does not provide

CloudTAK 13.111.3 has `oidc::enabled`, `oidc::enforced`, `oidc::name`, and `oidc::discovery` settings, and its login page links a "Sign in with ..." button to `/api/login/oidc`. Its API has no route there (upstream issue [#661](https://github.com/dfpc-coe/CloudTAK/issues/661)). The chart sets those settings with `CLOUDTAK_Config_*` variables, which CloudTAK writes to its settings table on start:

| Setting | Value | Effect |
| --- | --- | --- |
| `oidc::enabled`, `oidc::enforced` | `true` | `POST /api/login` returns 403. The login page shows only the Keycloak button |
| `oidc::name` | `UDS SSO` | Button text |
| `oidc::discovery` | `https://sso.<domain>/realms/uds/.well-known/openid-configuration` | The page shows a misconfiguration warning instead of the button without it |
| `passkey::enabled` | `false` | Hides the passkey button |

The route behind the button is `sso.mjs`, in a second container of the CloudTAK pod that listens only on `127.0.0.1:5002`. `start.sh` adds a `location ^~ /api/login/oidc` block for it in front of CloudTAK's `location ~ ^/api` (a `^~` prefix match is chosen before regular expressions). CloudTAK itself is not patched. `sso.mjs` imports CloudTAK's compiled model, user, and session modules from the image, so a CloudTAK upgrade that changes those modules needs a matching change here. The Renovate pull request for a new CloudTAK tag runs the sign-in test below.

CloudTAK cannot redirect to Keycloak on its own. The auto-redirect is the `auto.js` script, loaded with nginx `sub_filter`. `https://map.<domain>/login?sso=off` shows the login page without the redirect, with only the Keycloak button. After a failed Keycloak sign-in the browser lands there, and the `sso` container log has the reason.

### Trade-offs

- Authservice is not used. Authservice in front of CloudTAK would authenticate the page but CloudTAK would never see the Keycloak user. People would still need a TAK account and a second sign-in, and TAK would see that account instead of the Keycloak user. With the code flow in the pod, the Keycloak user is the CloudTAK user and the TAK certificate subject.
- The ID token is taken straight from Keycloak's token endpoint over a verified TLS connection, so `sso.mjs` checks its issuer, audience, nonce, and expiry rather than its signature (OpenID Connect Core 3.1.3.7). TAK checks the access token's signature against Keycloak's keys when it enrols the certificate.
- CloudTAK's logout clears the CloudTAK session but not the Keycloak session. The next visit goes through Keycloak and back without a password prompt while the Keycloak session lasts. Sign out of Keycloak at `https://sso.<domain>/realms/uds/account/` to end both.
- A CloudTAK session lasts as long as CloudTAK's refresh token (`login::refresh::expiry`, 720 hours by default), not the Keycloak session. Removing a user from `/UDS Core/Admin` in Keycloak blocks new sign-ins, not open CloudTAK sessions. Disable the profile in CloudTAK's admin page or revoke the certificate in TAK to cut one off.
- The TAK certificate is enrolled at each sign-in. CloudTAK keeps it for the session, the way it keeps one from a password sign-in.

## Admin account

CloudTAK's admin connection (connection 0) needs a TAK account and a certificate. The component creates one TAK file user, `cloudtak-admin`, in the TAK group `Operators`, and gives CloudTAK the TAK admin certificate for connection 0. Nobody signs in with that account: CloudTAK refuses password sign-in. Its password is `CLOUDTAK_PASSWORD` in Secret `cloudtak/cloudtak`.

## Bootstrap container

The `bootstrap` container runs [`bootstrap.mjs`](../.github/container-and-chart/cloudtak/bootstrap.mjs) in the CloudTAK pod. It calls CloudTAK on `127.0.0.1:5000`, inside the pod. Every five minutes it:

1. Tries the `cloudtak-admin` password against TAK's `/oauth/token` on 8447. If that fails, it creates the user through `/user-management/api/new-user` on 8443 with the admin certificate. TAK stores file users in `UserAuthenticationFile.xml` inside the API pod, and that file does not survive a restart of the API pod, so this check is what recreates the user.
2. If CloudTAK reports `unconfigured`, it sends `PATCH /api/server` with the TAK URLs, the admin certificate and an unencrypted copy of its key, and the `cloudtak-admin` credentials. CloudTAK accepts that call without a login only while it is unconfigured, so the window closes when the pod starts.

`node /home/etl/uds/bootstrap.mjs status` prints the server record. It authenticates with a five-minute token for `cloudtak-admin` signed with CloudTAK's `SigningSecret`, the form CloudTAK accepts as a server-minted token. It exits 0 only when `connection_status` is `live`.

The admin certificate is mounted only in the bootstrap container. The CloudTAK container gets only `ca.pem`. CloudTAK still stores the admin certificate and key in its database, because its admin connection (connection 0) uses them. Treat that database as holding a TAK admin credential.

## TAK connection

| CloudTAK setting | Value | Used for |
| --- | --- | --- |
| `url` | `ssl://takserver-messaging-service.takserver.svc.cluster.local:8089` | CoT streaming with client certificates |
| `api` | `https://takserver-api-service.takserver.svc.cluster.local:8443` | Marti API with client certificates |
| `webtak` | `https://takserver-web.takserver.svc.cluster.local:8447` | Certificate enrolment for each Keycloak sign-in (bearer token) and for the admin account (password) |

`webtak` is 8447, the connector the tenant gateway uses, rather than 8446. 8447 has a certificate whose SANs are the `takserver-web` Service names, so CloudTAK verifies it against the deploy-time CA (`NODE_EXTRA_CA_CERTS`). TAK's generated 8443 and 8089 server certificate names no in-cluster host. CloudTAK's TAK library does not verify the server certificate on its certificate-authenticated connections, as upstream ships it. The bootstrap container checks the 8443 chain against the CA and skips only the host name.

## Network rules

All rules are explicit. There is no `IntraNamespace` and no `Anywhere` rule in either `Package` CR.

| From | To | Port | Rule in |
| --- | --- | --- | --- |
| tenant gateway | `cloudtak` | 5000 | `cloudtak` expose |
| `cloudtak` | `cloudtak-postgis` | 5432 | `cloudtak` |
| `cloudtak` | `takserver-api` | 8443, 8447 | `cloudtak` Egress and `takserver` Ingress |
| `cloudtak` | `takserver-messaging` | 8089 | `cloudtak` Egress and `takserver` Ingress |
| `cloudtak` | tenant gateway (Keycloak) | 443 | `cloudtak` Egress |

There is no waypoint: the namespace is ambient and Authservice is not enabled. `chart/values.yaml` `cloudtak.enabled` renders the three `takserver` Ingress rules. They stay in place if the `cloudtak` component is not deployed, and then match no pods.

## Basemap

CloudTAK has no internet egress here, and no basemap is loaded. CloudTAK fetches basemap tiles on the server side (its CSP allows images only from itself), so a basemap that points at an internet tile service needs an egress rule for the CloudTAK pod. UDS Core can scope egress to a host name with `remoteHost`, which needs the UDS egress gateway. The slim development core does not include it. A fully offline basemap needs a PMTiles file in S3 and CloudTAK's tile service, which are not part of this component. The map, CoT markers, and overlays work without one.

## Tests

`uds run test:cloudtak` (part of `test:all`):

- waits for the PostGIS StatefulSet and the CloudTAK Deployment, and checks that every container is ready and no pod runs as uid 0
- checks that the `cloudtak` Package is `Ready`, has NetworkPolicies, and has no `Anywhere` or `IntraNamespace` rule
- checks that `https://map.uds.dev/login` loads the auto-redirect script, that `/api/login/oidc` is a 302 to the `uds-cloudtak` client on `sso.uds.dev` with PKCE, that `POST /api/login` is refused with 403, and that Secret `cloudtak-sso` exists
- runs `bootstrap.mjs status` in the pod until `connection_status` is `live`

`tests/cloudtak.spec.ts` (Playwright, in `test:ui`) opens `https://map.uds.dev/` in a new browser context and expects the Keycloak login for client `uds-cloudtak` with redirect `https://map.uds.dev/api/login/oidc/callback`. It signs in as the Keycloak test user `doug` (in `/UDS Core/Admin` and `/TAK/Operators_READ`) and waits for the map canvas on `map.uds.dev`, with no CloudTAK form in between. On a first sign-in CloudTAK asks for a callsign; the test enters the Keycloak username and skips the browser permission step. Then, with the CloudTAK session the browser holds, it checks that:

- `GET /api/login` returns the Keycloak username as the account (`email`)
- `GET /api/marti/group` returns 200 with at least one group. CloudTAK makes that call to TAK with the certificate it enrolled for the user
- `GET /api/server` has `connection_status: live` (connection 0)
- `GET /api/marti/clients` lists a connected TAK client for the user, which is the map's own streaming connection
- `/login?sso=off` shows "Sign in with UDS SSO" and no password or passkey form

It saves `cloudtak-01-keycloak.png`, `cloudtak-02-map.png`, and `cloudtak-03-login-page.png` under `tests/.playwright/screenshots`, which CI uploads with the Playwright report. `test:flows` also checks the flows inside the `cloudtak` namespace.

## License

CloudTAK is licensed under AGPL-3.0. This repository does not include its source: `upstream/cloudtak` is a submodule that points at the upstream repository, and the image's `org.opencontainers.image.source` and `org.opencontainers.image.revision` labels name the build. AGPL section 13 requires that users who interact with a modified CloudTAK over a network can get its source. The image changes only the start script and adds the sign-in and bootstrap scripts and two nginx fragments, all in this repository. CloudTAK's own code is not modified. Whoever runs a modified CloudTAK for others has to offer that source. The rest of this repository stays GPL-3.0-only.

## Resources

On the test node, CloudTAK requests 100m CPU and 384Mi memory with a 1Gi limit, the `sso` container 10m and 192Mi with a 512Mi limit (it loads CloudTAK's modules and sits near 270 MB), the bootstrap container 10m and 48Mi, and PostGIS 50m and 128Mi. The API's Node heap is capped at 640 MB with `NODE_OPTIONS`. Upstream asks for 6 GB.
