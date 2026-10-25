# CloudTAK

[CloudTAK](https://github.com/dfpc-coe/CloudTAK) is a browser map client for TAK Server. The optional `cloudtak` component runs it at `https://map.<domain>/`, next to the TAK web UI, and connects it to the TAK Server in the `takserver` namespace. The TAK Server deployment does not change, apart from three Ingress rules in its `Package` CR.

## What is deployed

| Object | Namespace | Purpose |
| --- | --- | --- |
| Deployment `cloudtak` | `cloudtak` | CloudTAK's nginx and API process on port 5000, plus the `sso` and `bootstrap` containers |
| StatefulSet `cloudtak-postgis` | `cloudtak` | CloudTAK's own PostGIS database, `ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:18-3.6` (amd64 and arm64, see [ADR 16](../adr/0016-upgrade-postgres-in-place.md)), 2Gi volume |
| Secret `cloudtak` | `cloudtak` | Session signing secret, database password, and the password of the TAK account behind the admin connection. Generated on first install and kept on upgrade |
| Secret `cloudtak-sso` | `cloudtak` | Keycloak client secret, key `OIDC_CLIENT_SECRET`. Written by the UDS operator |
| Secret `cloudtak-tak-admin` | `cloudtak` | `ca.pem`, `admin.pem`, and `admin.key`, copied from ConfigMap `takserver/cert-migration` by the component's `onDeploy` action |
| Package `cloudtak` | `cloudtak` | Keycloak client `uds-cloudtak` (name `CloudTAK Login`), the `map` host on the tenant gateway, and the allow list |

Upstream CloudTAK's compose file also runs a tile server, an events worker, a media server, a retention job, and an S3 store. None of those are deployed. Without S3, CloudTAK features that store files (imports, attachments, uploaded basemaps, data packages) do not work. The map, CoT from TAK, and the admin pages do.

## Image

The image is built from the `upstream/cloudtak` git submodule, pinned to tag `v13.112.3` (`745d8a9bcfebde48d7a97cc4e77aa0f4d827508a`), and published as `ghcr.io/jonathanagustin/uds-k3d-takserver/cloudtak:v13.112.3`. No upstream image is used.

[`.github/container-and-chart/cloudtak/`](../.github/container-and-chart/cloudtak/) holds the build:

- `docker-bake.hcl` builds CloudTAK's own `Dockerfile` from the submodule with no changes. Its first stage downloads the CloudTAK-Data `v1.2.0` release zip, which upstream pins in that file.
- `Dockerfile` copies the built API (with `npm prune --omit=dev`) and the built web app onto the same `nginx:alpine3.24` base with `nodejs-current`, `bash`, and `openssl`. The upstream image is about 2.2 GB because it keeps its compilers and build dependencies. This one is about 600 MB.
- `start.sh` replaces upstream `api/start`. It renders the same `nginx.conf`, drops the `user` directive, and moves the pid file, logs, and temp paths under `/tmp`. The container runs as uid 101 with a read-only root filesystem.
- `sso.mjs` is the `sso` container's Keycloak sign-in. `nginx-sso.conf` and `nginx-sso-head.conf` are the two nginx fragments `start.sh` adds for it. See [Sign-in](#sign-in).
- `bootstrap.mjs` is the bootstrap container's script. See below.
- `basemap.mjs` writes the tile proxy's nginx configuration and keeps the default basemap record. See [Basemap](#basemap).

`build.sh` refuses to build if the submodule is not at the pinned commit. The image is published for `linux/amd64` and `linux/arm64`, the same way as the TAK images (see [Building the images](building.md)). There is no QEMU:

- The inputs are the submodule commit plus the git tree of this directory, recorded in the `dev.uds-k3d-takserver.inputs` label. `<key>` is the first 12 hex digits of their SHA-256 (`build.sh --tag` prints `v13.112.3-<key>`).
- The Test workflow's `cloudtak-image` jobs run `ARCH=<arch> build.sh --if-changed` on a native runner for each architecture (`ubuntu-latest` and `ubuntu-24.04-arm`). Each job pushes `v13.112.3-<key>-<arch>`, and only when no image with those inputs exists yet.
- `cloudtak-index` then runs `build.sh --merge`. It writes `v13.112.3-<key>` as an index of the two tags with `docker buildx imagetools create`, and writes nothing unless both tags carry this commit's inputs.
- Before CI creates a package, `.github/scripts/pin-image-tags.sh` points `zarf.yaml` and the chart values at `v13.112.3-<key>` in the job's checkout. A keyed tag only ever holds one set of inputs, so a pull request tests its own CloudTAK image even when another branch builds a different one at the same time. The PostGIS image works the same way (`18-3.6-<key>`).
- `v13.112.3` and `v13.112.3-<arch>`, the tags in the committed files and in released packages, are written only from `main`. `build.sh --wait`, used by the Scan and Package workflows, waits for the keyed index.
- `.github/workflows/cloudtak-image.yaml` does the same on `main`.

A local `build.sh` builds the host architecture and loads it as `v13.112.3`.

Renovate's `git-submodules` manager follows CloudTAK release tags. The tag strings marked `# cloudtak-version` in `zarf.yaml`, `charts/cloudtak/`, and `docker-bake.hcl` move in the same pull request.

## Sign-in

People sign in to CloudTAK through UDS Core Keycloak, on the same UDS login page as the TAK web UI. CloudTAK's own password and passkey sign-in is off.

1. `https://map.<domain>/` loads the CloudTAK app. With no session, the app routes to `/login`. nginx adds `/api/login/oidc/auto.js` to the app's HTML pages. With no stored ID token, that script sends `/login` on to `/api/login/oidc`. After a sign-in it sends `/login` to `/api/login/oidc/logout` with the ID token as `id_token_hint`.
2. `/api/login/oidc` starts an authorization code flow with PKCE (S256) for Keycloak client `uds-cloudtak` in realm `uds`, and the browser lands on `https://sso.<domain>/realms/uds/protocol/openid-connect/auth`. The client allows members of `/UDS Core/Admin`, the same gate as the TAK client.
3. Keycloak returns to `https://map.<domain>/api/login/oidc/callback`. The `sso` container exchanges the code at Keycloak's token endpoint, in the cluster. `sso.<domain>` resolves to the tenant gateway through the in-cluster CoreDNS rewrite (see [Networking](networking.md)), and the Keycloak certificate is checked against the system trust store.
4. It enrols a TAK client certificate for the user on TAK's 8447. It sends the Keycloak access token as a bearer token, through the same TAK library call CloudTAK uses for password sign-in. TAK takes the username from `preferred_username` and the groups from `groups`, as it does for the TAK web UI (see [Single sign-on](sso.md)). The certificate is the Keycloak user's own TAK identity, with that user's TAK groups.
5. It creates or updates the CloudTAK profile for that username with the certificate, and opens a CloudTAK login session with CloudTAK's own session code. Members of `sso.adminGroup` (default `/UDS Core/Admin`) become CloudTAK system administrators.
6. The browser gets the session (login token, refresh token, session id) in the URL fragment of `/api/login/oidc/finish`, which is not sent to any server or written to a log. That page stores them where CloudTAK's own login page does and opens the map. The app restores the session, rotates the refresh token, and opens its own streaming connection to TAK's 8089 with the user's certificate.

### What CloudTAK does and does not provide

CloudTAK 13.112.3 has `oidc::enabled`, `oidc::enforced`, `oidc::name`, and `oidc::discovery` settings, and its login page links a "Sign in with ..." button to `/api/login/oidc`. Its API has no route there (upstream issue [#661](https://github.com/dfpc-coe/CloudTAK/issues/661)). The chart sets those settings with `CLOUDTAK_Config_*` variables, which CloudTAK writes to its settings table on start:

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
- CloudTAK's own logout clears the CloudTAK session and opens `/login`. `auto.js` sends that to `/api/login/oidc/logout` with the ID token from sign-in as `id_token_hint`. The client sets `logout.confirmation.enabled` to `false`. UDS Core otherwise leaves that on, and Keycloak 26 then shows "You are logged out" instead of following `post_logout_redirect_uri`. With it off, Keycloak ends the session and redirects back to the sign-in route, so the next visit stops on the Keycloak login page. Without the hint Keycloak stays on its confirmation page and does not continue. `auto.js` drops the CloudTAK login token, refresh token, and session id before that redirect, so the next load cannot refresh the old session. A CloudTAK session that never opens `/login` still lasts until its refresh token expires. Password sign-in and passkey sign-in stay off.
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
| `cloudtak` (service account `cloudtak`) | `tile.openstreetmap.org` | 443 | `cloudtak` Egress `remoteHost`, only with `basemap.enabled` |

The namespace has no waypoint of its own: it is ambient and Authservice is not enabled. The basemap rule uses UDS Core's shared egress waypoint in `istio-egress-ambient`. The UDS operator creates a ServiceEntry for the tile host and an AuthorizationPolicy that admits only the `cloudtak` service account. `charts/takserver/values.yaml` `cloudtak.enabled` renders the three `takserver` Ingress rules. They stay in place if the `cloudtak` component is not deployed, and then match no pods.

`additionalNetworkAllow` in `charts/cloudtak/values.yaml` appends deployer rules after these, the same as in the `takserver` chart. Each entry needs a unique `description`.

## Basemap

New users get OpenStreetMap as their default basemap. CloudTAK fetches the basemap's tiles through nginx in its own container, which proxies and caches them from the tile host. See [ADR 11](../adr/0011-cloudtak-default-basemap-through-a-tile-proxy.md) for why it is not CloudTAK's own tile route.

- The browser asks for `https://map.<domain>/uds-basemap/tiles/{z}/{x}/{y}?token=<session>`. nginx checks the token with CloudTAK, so only signed-in users get tiles. Zoom levels outside `minzoom`..`maxzoom` get 404, and a session that asks for more than 20 tiles a second after a burst of 200 gets 429.
- nginx sends the tile host only Host, Accept, the browser's Referer, and a User-Agent such as `CloudTAK/13.112.3 (uds-k3d-takserver; +https://github.com/jonathanagustin/uds-k3d-takserver; contact: <basemap.contact>)`. It verifies the host's TLS certificate.
- Tiles are cached in the pod's `/tmp` (`cacheSize`, default 256m), for as long as the tile host's cache headers allow, or 7 days when it sends none. Responses carry `X-Cache-Status`.
- The bootstrap container creates the server basemap record "OpenStreetMap" with the attribution "© OpenStreetMap contributors", and sets it as CloudTAK's default basemap (`map::basemap`). It updates the record when the settings change. Users who signed in before keep their basemap and can choose this one in the basemap menu.
- The Package allows egress to the tile host on its port only, from the `cloudtak` service account (see [Network rules](#network-rules)).

The OpenStreetMap tile servers are run by donations, with no service level, under the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/). Its rules for a caching proxy are met by the headers, the cache, and the rate limit above. The policy also asks for a contactable User-Agent: set `basemap.contact` to an email address or URL for your deployment. For heavy use, use another provider or your own tile server.

Settings, under `basemap` in `charts/cloudtak/values.yaml` (set them with UDS bundle overrides on chart `uds-cloudtak`):

| Value | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | `false` removes the basemap record, the proxy, and the egress rule |
| `url` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Tile URL template, http or https, with `{z}`, `{x}`, and `{y}` |
| `name` | `OpenStreetMap` | Name in CloudTAK's basemap list |
| `attribution` | `© OpenStreetMap contributors` with a link | Shown on the map. HTML |
| `minzoom`, `maxzoom` | `0`, `19` | Zoom levels served |
| `default` | `true` | Make it CloudTAK's default basemap for new users |
| `contact` | empty | Email or URL added to the User-Agent |
| `userAgent` | empty | Replaces the whole User-Agent |
| `cacheSize` | `256m` | Disk cache size |
| `rate`, `burst` | `20`, `200` | Tiles a second per session, after a burst |
| `port` | from `url` | Port of the egress rule |
| `egress` | `{}` | Replaces the `remoteHost` rule, for a tile server in the cluster, such as `{remoteNamespace: tiles, remoteSelector: {app: tileserver}, port: 8080}` |

Air-gapped installs: set `basemap.enabled: false`, or point `basemap.url` at a tile server in the network. A server outside the cluster gets a `remoteHost` rule for its host. For one inside the cluster, use its Service's full name in `url` and set `egress`. A server with a private CA needs that CA in the image's bundle (`/etc/ssl/certs/ca-certificates.crt`), or plain http.

CloudTAK's own tile route for this record (`/api/basemap/:id/tiles/:z/:x/:y`) refuses the private address the tile host resolves to in the mesh. The web map does not use it for this basemap, but server-side tile features do. Uploaded basemaps and fully offline PMTiles need S3 and CloudTAK's tile service, which are not part of this component.

## Tests

`uds run test:cloudtak` (part of `test:all`):

- waits for the PostGIS StatefulSet and the CloudTAK Deployment, and checks that every container is ready and no pod runs as uid 0
- checks that the `cloudtak` Package is `Ready`, has NetworkPolicies, and has no `Anywhere` or `IntraNamespace` rule
- checks that `https://map.uds.dev/login` loads the auto-redirect script, that `/api/login/oidc` is a 302 to the `uds-cloudtak` client on `sso.uds.dev` with PKCE, that `POST /api/login` is refused with 403, and that Secret `cloudtak-sso` exists
- runs `bootstrap.mjs status` in the pod until `connection_status` is `live`
- with the basemap on, checks that the Package has one `remoteHost` rule, that `istio-egress-ambient` has a ServiceEntry for that host, and that `bootstrap.mjs basemap` finds the basemap record as the default and gets tile 0/0/0 back as an image through the proxy

`tests/cloudtak.spec.ts` (Playwright, in `test:ui`) opens `https://map.uds.dev/` in a new browser context and expects the Keycloak login for client `uds-cloudtak` with redirect `https://map.uds.dev/api/login/oidc/callback`. It signs in as the Keycloak test user `doug` (in `/UDS Core/Admin` and `/TAK/Operators_READ`) and waits for the map canvas on `map.uds.dev`, with no CloudTAK form in between. On a first sign-in CloudTAK asks for a callsign; the test enters the Keycloak username and skips the browser permission step. Then, with the CloudTAK session the browser holds, it checks that:

- `GET /api/login` returns the Keycloak username as the account (`email`)
- `GET /api/marti/group` returns 200 with at least one group. CloudTAK makes that call to TAK with the certificate it enrolled for the user
- `GET /api/server` has `connection_status: live` (connection 0)
- `GET /api/marti/clients` lists a connected TAK client for the user, which is the map's own streaming connection
- the server basemap with the `/uds-basemap/tiles/` URL exists, the map loads its tiles (200, `image/*`), the attribution box names OpenStreetMap, and a tile request without the session token gets 401
- zooming in with the mouse wheel loads tiles at a higher zoom
- `/login?sso=off` shows "Sign in with UDS SSO" and no password or passkey form

It saves `cloudtak-01-keycloak.png`, `cloudtak-02-map.png`, `cloudtak-04-basemap.png` (after the zoom), and `cloudtak-03-login-page.png` under `tests/.playwright/screenshots`, which CI uploads with the Playwright report. `test:flows` also checks the flows inside the `cloudtak` namespace.

## License

CloudTAK is licensed under AGPL-3.0. This repository does not include its source: `upstream/cloudtak` is a submodule that points at the upstream repository, and the image's `org.opencontainers.image.source` and `org.opencontainers.image.revision` labels name the build. AGPL section 13 requires that users who interact with a modified CloudTAK over a network can get its source. The image changes only the start script and adds the sign-in, bootstrap, and basemap scripts and the nginx fragments, all in this repository. CloudTAK's own code is not modified. Whoever runs a modified CloudTAK for others has to offer that source. The rest of this repository stays GPL-3.0-only.

## Resources

On the test node, CloudTAK requests 100m CPU and 384Mi memory, with a 1Gi limit. The `sso` container requests 10m and 192Mi, with a 512Mi limit. It loads CloudTAK's modules and sits near 270 MB. The bootstrap container requests 10m and 48Mi. PostGIS requests 50m and 128Mi. The API's Node heap is capped at 640 MB with `NODE_OPTIONS`. Upstream asks for 6 GB.
