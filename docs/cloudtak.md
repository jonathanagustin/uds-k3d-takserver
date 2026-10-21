# CloudTAK

[CloudTAK](https://github.com/dfpc-coe/CloudTAK) is a browser map client for TAK Server. The optional `cloudtak` component runs it at `https://map.<domain>/`, next to the TAK web UI, and connects it to the TAK Server in the `takserver` namespace. The TAK Server deployment does not change, apart from three Ingress rules in its `Package` CR.

## What is deployed

| Object | Namespace | Purpose |
| --- | --- | --- |
| Deployment `cloudtak` | `cloudtak` | CloudTAK's nginx and API process on port 5000, plus the `bootstrap` container |
| StatefulSet `cloudtak-postgis` | `cloudtak` | CloudTAK's own PostGIS database, `postgis/postgis:15-3.4`, 2Gi volume |
| Secret `cloudtak` | `cloudtak` | Session signing secret, database password, and the TAK account password. Generated on first install and kept on upgrade |
| Secret `cloudtak-tak-admin` | `cloudtak` | `ca.pem`, `admin.pem`, and `admin.key`, copied from ConfigMap `takserver/cert-migration` by the component's `onDeploy` action |
| Package `cloudtak` | `cloudtak` | Keycloak client through Authservice, the `map` host on the tenant gateway, and the allow list |

Upstream CloudTAK's compose file also runs a tile server, an events worker, a media server, a retention job, and an S3 store. None of those are deployed. Without S3, CloudTAK features that store files (imports, attachments, uploaded basemaps, data packages) do not work. The map, CoT from TAK, and the admin pages do.

## Image

The image is built from the `upstream/cloudtak` git submodule, pinned to tag `v13.111.3` (`2b706cee75428788edcf010ec6bf2b5433f29a83`), and published as `ghcr.io/jonathanagustin/uds-k3d-takserver/cloudtak:v13.111.3`. No upstream image is used.

[`.github/container-and-chart/cloudtak/`](../.github/container-and-chart/cloudtak/) holds the build:

- `docker-bake.hcl` builds CloudTAK's own `Dockerfile` from the submodule with no changes. Its first stage downloads the CloudTAK-Data `v1.2.0` release zip, which upstream pins in that file.
- `Dockerfile` copies the built API (with `npm prune --omit=dev`) and the built web app onto the same `nginx:alpine3.24` base with `nodejs-current`, `bash`, and `openssl`. The upstream image is about 2.2 GB because it keeps its compilers and build dependencies. This one is about 600 MB.
- `start.sh` replaces upstream `api/start`. It renders the same `nginx.conf`, drops the `user` directive, and moves the pid file, logs, and temp paths under `/tmp`. The container runs as uid 101 with a read-only root filesystem.
- `bootstrap.mjs` is the bootstrap container's script. See below.

`build.sh` refuses to build if the submodule is not at the pinned commit. The Test workflow's `images` job runs `build.sh --if-changed`, which builds and pushes only when the published image's `dev.uds-k3d-takserver.inputs` label differs from the submodule commit plus the git tree of that directory. `.github/workflows/cloudtak-image.yaml` does the same on `main`.

Renovate's `git-submodules` manager follows CloudTAK release tags. The tag strings marked `# cloudtak-version` in `zarf.yaml`, `cloudtak/chart/`, and `docker-bake.hcl` move in the same pull request.

## Sign-in

There are two sign-ins, and the second one is not Keycloak.

1. **Keycloak, through Authservice.** The `Package` CR sets `enableAuthserviceSelector: {app: cloudtak}`. In ambient mode the UDS operator puts a waypoint in front of the `cloudtak` Service, and Authservice redirects any request without a session to Keycloak, including `/api` calls. The Keycloak client is `uds-cloudtak`, and only members of `/UDS Core/Admin` get through. The callback is `https://map.<domain>/oauth2/callback`, which Authservice owns.
2. **CloudTAK, with a TAK account.** CloudTAK then shows its own sign-in page. CloudTAK sends the username and password to TAK's `/oauth/token` password grant and enrolls a client certificate for that user. TAK checks that grant only against its own file or LDAP users, not Keycloak. The component creates one TAK file user, `cloudtak-admin`, in the TAK group `Operators`, and makes it the CloudTAK system administrator. Its password is `CLOUDTAK_PASSWORD` in Secret `cloudtak/cloudtak`:

   ```bash
   uds zarf tools kubectl get secret cloudtak -n cloudtak -o jsonpath='{.data.CLOUDTAK_PASSWORD}' | base64 -d
   ```

CloudTAK 13.111.3 has settings and a button for OpenID Connect, but the API has no `/api/login/oidc` route behind them (upstream issue [#661](https://github.com/dfpc-coe/CloudTAK/issues/661)). So the Keycloak identity does not reach CloudTAK, and CloudTAK users are TAK accounts. TAK itself already accepts Keycloak bearer tokens for certificate enrollment (see [sso.md](sso.md)), so a CloudTAK route that accepted the Authservice token would remove the second sign-in. That is an upstream change, not something this package can configure.

## Bootstrap container

The `bootstrap` container runs [`bootstrap.mjs`](../.github/container-and-chart/cloudtak/bootstrap.mjs) in the CloudTAK pod. It calls CloudTAK on `127.0.0.1:5000`, so its requests never go through the waypoint or Authservice. Every five minutes it:

1. Tries the `cloudtak-admin` password against TAK's `/oauth/token` on 8447. If that fails, it creates the user through `/user-management/api/new-user` on 8443 with the admin certificate. TAK stores file users in `UserAuthenticationFile.xml` inside the API pod, and that file does not survive a restart of the API pod, so this check is what recreates the user.
2. If CloudTAK reports `unconfigured`, it sends `PATCH /api/server` with the TAK URLs, the admin certificate and an unencrypted copy of its key, and the `cloudtak-admin` credentials. CloudTAK accepts that call without a login only while it is unconfigured, so the window closes when the pod starts.

`node /home/etl/uds/bootstrap.mjs status` signs in as `cloudtak-admin` and prints the server record. It exits 0 only when `connection_status` is `live`.

The admin certificate is mounted only in the bootstrap container. The CloudTAK container gets only `ca.pem`. CloudTAK still stores the admin certificate and key in its database, because its admin connection (connection 0) uses them. Treat that database as holding a TAK admin credential.

## TAK connection

| CloudTAK setting | Value | Used for |
| --- | --- | --- |
| `url` | `ssl://takserver-messaging-service.takserver.svc.cluster.local:8089` | CoT streaming with client certificates |
| `api` | `https://takserver-api-service.takserver.svc.cluster.local:8443` | Marti API with client certificates |
| `webtak` | `https://takserver-web.takserver.svc.cluster.local:8447` | Password sign-in and certificate enrollment |

`webtak` is 8447, the connector the tenant gateway uses, rather than 8446. 8447 has a certificate whose SANs are the `takserver-web` Service names, so CloudTAK verifies it against the deploy-time CA (`NODE_EXTRA_CA_CERTS`). TAK's generated 8443 and 8089 server certificate names no in-cluster host. CloudTAK's TAK library does not verify the server certificate on its certificate-authenticated connections, as upstream ships it. The bootstrap container checks the 8443 chain against the CA and skips only the host name.

## Network rules

All rules are explicit. There is no `IntraNamespace` and no `Anywhere` rule in either `Package` CR.

| From | To | Port | Rule in |
| --- | --- | --- | --- |
| tenant gateway | `cloudtak` | 5000 | `cloudtak` expose (through the Authservice waypoint) |
| `cloudtak` | `cloudtak-postgis` | 5432 | `cloudtak` |
| `cloudtak` | `takserver-api` | 8443, 8447 | `cloudtak` Egress and `takserver` Ingress |
| `cloudtak` | `takserver-messaging` | 8089 | `cloudtak` Egress and `takserver` Ingress |

The operator adds the waypoint and Authservice rules for the SSO client. `chart/values.yaml` `cloudtak.enabled` renders the three `takserver` Ingress rules. They stay in place if the `cloudtak` component is not deployed, and then match no pods.

## Basemap

CloudTAK has no internet egress here, and no basemap is loaded. CloudTAK fetches basemap tiles on the server side (its CSP allows images only from itself), so a basemap that points at an internet tile service needs an egress rule for the CloudTAK pod. UDS Core can scope egress to a host name with `remoteHost`, which needs the UDS egress gateway. The slim development core does not include it. A fully offline basemap needs a PMTiles file in S3 and CloudTAK's tile service, which are not part of this component. The map, CoT markers, and overlays work without one.

## Tests

`uds run test:cloudtak` (part of `test:all`):

- waits for the PostGIS StatefulSet and the CloudTAK Deployment, and checks that every container is ready and no pod runs as uid 0
- checks that the `cloudtak` Package is `Ready`, has NetworkPolicies, and has no `Anywhere` or `IntraNamespace` rule
- checks that `/` and `/api/server` on `map.uds.dev` without a session are a 302 to Keycloak
- runs `bootstrap.mjs status` in the pod until `connection_status` is `live`

`tests/cloudtak.spec.ts` (Playwright, in `test:ui`) opens `https://map.uds.dev/` in a new browser context, signs in to Keycloak as the test user `doug`, signs in to CloudTAK as `cloudtak-admin`, waits for the map canvas, and reads `/api/server` through the gateway. It saves `cloudtak-01-keycloak.png`, `cloudtak-02-login.png`, and `cloudtak-03-map.png` under `tests/.playwright/screenshots`, which CI uploads with the Playwright report. `test:flows` also checks the flows inside the `cloudtak` namespace.

## License

CloudTAK is licensed under AGPL-3.0. This repository does not include its source: `upstream/cloudtak` is a submodule that points at the upstream repository, and the image's `org.opencontainers.image.source` and `org.opencontainers.image.revision` labels name the build. AGPL section 13 requires that users who interact with a modified CloudTAK over a network can get its source. The image changes only the start script and adds the bootstrap script, both in this repository. Whoever runs a modified CloudTAK for others has to offer that source. The rest of this repository stays GPL-3.0-only.

## Resources

On the test node, CloudTAK requests 100m CPU and 384Mi memory with a 1Gi limit, the bootstrap container 10m and 48Mi, and PostGIS 50m and 128Mi. The Authservice waypoint is one more pod in the namespace. The API's Node heap is capped at 640 MB with `NODE_OPTIONS`. Upstream asks for 6 GB.
