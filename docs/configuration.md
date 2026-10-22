# Configuration

The package deploys the public TAK Server chart from [TAK-Product-Center/Server](https://github.com/TAK-Product-Center/Server) tag `5.7-RELEASE-14`, path `src/takserver-cluster/deployments/helm`. The chart is not copied into this repository. `common/zarf.yaml` points Zarf at that git URL. The chart version in that tag is `4.5.0`. It has no `values.yaml`. Its examples are `developer-values.yaml` and `production-values.yaml`.

The flavor is `upstream`. `uds run create-dev-package` passes `--flavor upstream`.

## Values

`values/common-values.yaml` is the overlay. `values/upstream-values.yaml` is an extra values file on the chart. Zarf replaces `###ZARF_VAR_DOMAIN###` and `###ZARF_VAR_TAK_IMAGE_TAG###` when the package is created.

| Variable | Default | Used for |
| --- | --- | --- |
| `DOMAIN` | `uds.dev` | Gateway hosts, such as `takserver.uds.dev` |
| `TAK_IMAGE_TAG` | `5.7-RELEASE-14` | The six images under `ghcr.io/jonathanagustin/uds-k3d-takserver` |
| `IN_CLUSTER_DNS` | `true` | On uds-k3d, add CoreDNS rewrites so `DOMAIN` hosts resolve to the Istio gateways inside the cluster. See [Networking](networking.md#in-cluster-dns) |
| `PASSTHROUGH_HOSTS` | `takserver-api takserver-stream` | Hosts under `DOMAIN` that resolve to the passthrough gateway inside the cluster |

Postgres is `ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:15-3.4`, built in this repository from the official `postgres` image with PostGIS 3.4.3 for amd64 and arm64. The upstream chart's `postgis/postgis:15-3.4` is amd64 only. See [ADR 13](../adr/0013-build-the-postgis-image-here.md). NATS stays the images rendered by the upstream NATS chart. This repository does not build those.

The overlay turns the chart's nginx ingress off. The UDS Package in `charts/takserver/templates/uds-package.yaml` exposes the same ports through the passthrough gateway:

- `https://takserver.uds.dev` on the tenant gateway to `takserver-web` port 8447. The gateway re-encrypts and verifies TAK's certificate.
- `https://takserver.uds.dev` on the passthrough gateway to `takserver-api-service` port 8446
- `https://takserver-api.uds.dev` to `takserver-api-service` port 8443
- `https://takserver-stream.uds.dev` to `takserver-messaging-service` port 8089

`k3d-core-slim-dev` does not select `istio-passthrough-gateway`. `bundle/uds-bundle.yaml` lists `core-base` `1.15.0-upstream` with that optional component, so the test deploy upgrades the slim install and turns the gateway on. `bundle/test-values.yaml` is applied only by that bundle and lowers TAK CPU and memory for a 2 vCPU, 8 GB runner.

## Upstream chart values

The TAK chart is used as published. Nothing under `src/takserver-cluster/deployments/helm` is copied into this repo. `charts/takserver/` is only the UDS Package and the ConfigMaps that chart mounts. It is not a fork of the TAK templates.

The chart has no defaults file. `developer-values.yaml` in tag `5.7-RELEASE-14` is the example these overrides are measured against. Probes are hardcoded in the upstream Deployments (`api-readiness.sh`, `config-readiness.sh`, `messaging-readiness.sh`, and the TCP liveness ports). This repo does not replace those templates. The readiness scripts read `/logs/takserver-api.log`, `/logs/takserver-config.log`, and `UserAuthenticationFile.xml`. Logback writes `logs/takserver-*.log` and the image working directory is `/`, so that path is `/logs/takserver-*.log`. The file is absent until the process gets past Ignite discovery. `cat: /logs/takserver-api.log: No such file or directory` is that startup window, or a container that just restarted. It is not a different log path.

The cluster scripts pass `-XX:MaxRAMPercentage` and do not pass `-Xmx`. `setenv-cluster.sh` defaults that percentage to 90. The non-cluster `setenv.sh` instead divides host `MemTotal` into heap megabytes, and the image does not use that script. On OpenJDK 17.0.16, `UseContainerSupport` reports a 1Gi cgroup limit and still leaves `MaxHeapSize` at a fraction of host RAM, so the percentage does not keep the heap inside the limit. The image inserts `-Xms512m -Xmx512m` into the api, messaging, and config cluster scripts. `-Xmx` wins over `MaxRAMPercentage`. 512m is the heap Ignite's own warning asks for. A config process on the test runner logged `Runtime.maxMemory()` as 536870912. `ignite.sh` sets `-Xms1g -Xmx1g` only when `JVM_OPTS` is empty, and the chart always sets `JVM_OPTS`, so the server had no heap flag. The overlay sets `-Xmx512m` and caps the default data region at 128MiB. Those flags are not exported through `JDK_JAVA_OPTIONS`, because that variable also applies to `UserManager.jar`. With UserManager capped at `-Xmx128m`, the messaging container was still OOM-killed about 15 seconds after `Server started`: the 512m heap, metaspace, the 128MB off-heap cap, and the second JVM did not fit in 1Gi. The messaging Deployment copies `takserver.api.resources.limits`, so the overlay sets that limit to 1536Mi. `enable_admin.sh` runs UserManager with `-Xmx128m`. The mounted `TAKIgniteConfig.xml` sets `cacheOffHeapInitialSizeBytes` to 67108864 and `cacheOffHeapMaxSizeBytes` to 134217728 so the 0.99 factor cannot reserve another heap-sized off-heap. The image also creates `/work` (Tomcat's work directory under the `/` base) and ships an empty `UserAuthenticationFile.xml`. That file has no certificate fingerprint. `enable_admin.sh` runs `UserManager certmod -A` on `certs/files/admin.pem` after the server logs `Server started`. The messaging readiness script accepts `ROLE_ADMIN` in the file or the log line `adding new file-based user`, then still checks Postgres with the upstream `nc` command.

| Value | Developer example | This overlay | Why |
| --- | --- | --- | --- |
| `takserver.{api,messaging,config,plugins}.image` and `takserverDatabaseSetup.image` | `docker-devtest-local.artifacts.tak.gov/...` | `ghcr.io/jonathanagustin/uds-k3d-takserver/...` and `###ZARF_VAR_TAK_IMAGE_TAG###` | The example registry is private. These are the images built from the same tag. |
| `ignite.image` | tag `2.17.0` on the chart's tak.gov repository | this repo's `takserver-ignite` tag | Same Ignite version, built here. |
| `takserver.api.resources` and the messaging limits | request and limit 1 CPU and 8Gi | `values/common-values.yaml`: API request 250m and 1Gi, limit 1 CPU and 1536Mi. Messaging requests match; its own limit is ignored. `bundle/test-values.yaml`: API request 50m and 512Mi, messaging request 50m and 640Mi, CPU limit 500m, memory limit 1536Mi | The example does not schedule on a 2 vCPU, 8 GB runner. CPU requests stay low. The messaging template copies the API memory limit. 1536Mi holds the 512m heap, metaspace, the 128MB off-heap cap, and UserManager. A 1Gi cgroup OOM-killed that pod. The messaging request adds the 128m UserManager heap. |
| `takserver.config.resources` | unset | common values: request 250m and 1Gi, limit 1 CPU and 1Gi. test values: request 50m and 512Mi, limit 500m and 1Gi | The example does not set config resources. Config does not run UserManager. The request is the measured 512MB heap. 1Gi holds that heap and the off-heap cap. |
| `takserver.plugins.resources.requests.cpu` | 1 | 100m in common values, 25m in test values. The post-helm patch sets memory request 128Mi and limit 384Mi | The plugins template reads this CPU request and then uses the API CPU limit. It ignores plugin memory. The patch supplies the memory. The heap is `-Xmx128m`. |
| `ignite.replicaCount` | chart default 2 | 1 | A second Ignite pod does not fit next to the slim core. |
| `ignite.resources` | unset | common values: request 250m and 768Mi, limit 1 CPU and 1536Mi. test values: request 50m and 512Mi, limit 1 CPU and 1536Mi | `-Xmx512m`, 128m metaspace, and a 384 MiB data region. A 128 MiB region ran out of memory (`IgniteOutOfMemoryException`) during the API smoke test. 1536Mi is the limit those fit inside. |
| `ignite.serviceAccount.name` | `takserver-ignite` | `takserver-ignite` | Unchanged. The API, messaging, config, and plugins Deployments also use that account, and the Package allows those pod labels to reach the Kubernetes API. |
| `nats.replicaCount`, `nats.cluster`, `nats.config.cluster`, `nats.natsBox.enabled` | jetstream on, cluster on, 3 replicas, toolbox default on | 1 replica, clustering off, toolbox off | The toolbox crash-looped and blocked Helm. TAK does not use it. |
| `global.postgresql` and `postgresql.auth` | host, port, username, password, database | same, plus `postgresPassword` and the Bitnami username keys | Bitnami PostgreSQL 12.1.6 reads `auth.postgresPassword`. The mounted CoreConfig already points at `takserver-postgresql`. |
| `postgresql.image` | `docker.io/postgis/postgis:15-3.4` | `ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:15-3.4` | PostgreSQL 15 and PostGIS 3.4.3, built here for amd64 and arm64. The upstream image is amd64 only. |
| `takserver.ingress.enabled` | false | false | Unchanged. The UDS Package exposes the same ports on the passthrough gateway. |
| `imagePullSecret`, `certConfigMapName`, `coreConfigMapName` | `reg-cred`, `cert-migration`, `core-config` | same | Unchanged. |
| `takIgniteConfigMapName` | unset in the example, required by the template | `tak-ignite-config` | The chart mounts `TAKIgniteConfig.xml` from this name. |

`values/upstream-values.yaml` is empty.

## Single sign-on

`sso.enabled` registers Keycloak client `uds-takserver` and writes Secret `takserver-sso` with key `TAK_OIDC_CLIENT_SECRET`. The mounted `CoreConfig.xml` keeps that name as `${TAK_OIDC_CLIENT_SECRET}`. The upstream chart cannot add an init container, so the `takserver-oidc` Pepr module adds one that runs `envsubst` into `/conf/CoreConfig.xml` to each config, messaging, API, and plugins pod when the pod is created. The browser UI is tenant-gateway host `takserver` on port 8447. 8447 is a TLS connector, and the gateway connects to it over TLS. `api.web.backendTLS.enabled` (default `true`) controls that. See [Networking](networking.md). Ports 8443 and 8089 stay on client certificates. 8446 stays passthrough for enrollment. Authservice is not used. Group `/UDS Core/Admin` in the token's `groups` claim is `ROLE_ADMIN`. Groups under `/TAK/` are the TAK groups. See [Single sign-on](sso.md).

## What the chart mounts

`charts/takserver/templates/prereqs.yaml` creates ConfigMaps `core-config` and `tak-ignite-config`, Secret `reg-cred`, and Exemption `takserver-db-setup` in `uds-policy-exemptions`. A pre-install Job creates ConfigMap `cert-migration` when that object is missing and publishes ConfigMap `ignite-extensions` from the jar in the `takserver-config` image. The image build produces that jar with `:takserver-cluster:igniteExtensions`. Zarf installs this chart before the upstream chart, because a manifest in the same component would run only after that chart finished. The upstream chart mounts those ConfigMaps and always sets `imagePullSecrets` to `reg-cred`.

The upstream `post-install-hook-postgres.yaml` Job is named `takserver-db-setup` and sets `proxy.istio.io/config` to `{ "holdApplicationUntilProxyStarts": true }`. There is no values key for that annotation. UDS `RestrictIstioSidecarOverrides` denied every pod the Job created, so the schema hook never ran and Helm hit its 15 minute deadline with the Job still `0/1`. The Exemption matches pods `^takserver-db-setup-.*` in the release namespace and allows only that policy. Probes stay the upstream delays and ports. The messaging restarts on that run were the 1Gi OOM above, not the TCP liveness timing: the container exited about 15 seconds after UserManager started, before six liveness failures could accumulate.

`core-config` is the upstream cluster example. The Postgres URL is `jdbc:postgresql://takserver-postgresql:5432/cot` with user and password `postgres`. The chart mounts `CoreConfig.xml` read-only, so that URL is already substituted.

## Certificates

No private key, keystore, CSR, or CRL is stored in this repository. `charts/takserver/values.yaml` `certs` sets the CA subject (`uds-tak-ca`, `VA`, `Arlington`, `TAK`, `UDS`). The pre-install Job `takserver-cert-init` runs `/opt/tak/certs/publish-cert-configmap.sh` in the `takserver-config` image. That script runs the same steps as TAK's `generateClusterCerts.sh` from tag `5.7-RELEASE-14` (`makeRootCa.sh` and `makeCert.sh` for the server, admin, and user) and POSTs ConfigMap `cert-migration`. The upstream chart mounts that ConfigMap. The keystore password stays the upstream example value `atakatak`, which is also `CAPASS` in `cert-metadata.sh` and the password on the generated `admin.key`. Changing it means editing `CoreConfig.xml` and the Job together.

`certs.pkcs12` sets the format of the `.p12` files. `modern`, the default, passes TAK's `--fips` flag, so every `.p12` uses PBES2 (PBKDF2, AES-256-CBC) with an HMAC-SHA256 MAC, and the Job fails if one doesn't. `legacy` is TAK's own OpenSSL 3 output (`-legacy`: RC2 or 3DES with a SHA-1 MAC). The `.jks` keystores TAK Server loads are written by the JDK 17 `keytool` as PKCS#12 with AES-256-CBC and HMAC-SHA256 in both modes, including `takserver-web.jks` from `issue-web-cert.sh`. TAK opens them with `keystore="JKS"` through the JDK's keystore compatibility mode. In `modern` mode `makeRootCa.sh` also writes `truststore-root-legacy.p12`, which holds only the public CA certificate. The Job records the format in the ConfigMap annotation `uds.dev/pkcs12-format`, and `uds run test:pkcs12` checks every keystore when it says `modern`. The setting only applies when the Job generates the CA, so an upgrade keeps the existing files.

Android can't import a PKCS#12 file that uses AES on at least versions 9 through 13. For an Android ATAK device, export its certificate from PEM in the old format, for example `openssl pkcs12 -export -legacy -in device.pem -inkey device.key -certfile ca.pem -out device.p12`, rather than setting `legacy` for the whole deployment.

If ConfigMap `cert-migration` already exists, the Job leaves it alone. That is how an operator supplies certificates. Zarf `sensitive: true` variables are a poor fit for a directory of keystores, so this package does not take the key material as package variables.

`uds run test-install` does not create the ConfigMap first, so CI generates it at deploy time. The smoke and Playwright tasks read `admin.pem` and `admin.key` back out of the ConfigMap.

Older commits of this branch still contain the keystores that used to live in `chart/files/certs`. The working tree does not. A public copy of the repository needs a history that never had those files.

## Metrics

TAK Server `5.7-RELEASE-14` sets `management.endpoints.web.exposure.include=*` in `application.properties` and depends on `spring-boot-starter-actuator`, `micrometer-core`, and `micrometer-registry-cloudwatch2`. It does not depend on `micrometer-registry-prometheus`. The actuator endpoints are on the same HTTPS connectors as Marti (8443 and 8446). 8443 requires a client certificate. The API Service has no metrics port. The Package has no `monitor` entry, because a ServiceMonitor would not scrape a Prometheus text endpoint. `k3d-core-slim-dev` does not install the Prometheus operator.

## Logging

TAK writes its process log to stdout and to `/logs/takserver-*.log`. UDS Core's Vector and Loki collectors ship in the standard `core` package, not in `core-base` / `k3d-core-slim-dev`. This bundle does not add a second log agent. When the standard logging package is installed, Vector already tails pod stdout, which is the same stream `kubectl logs` reads. The test task requires a TAK startup line in that stream. It queries Loki only when a Loki Service is present.

## Pod security

The upstream Deployments do not set `securityContext`, and the chart has no value for `runAsNonRoot` or a read-only root filesystem. The images run as root. TAK and the cert scripts write `/certs`, `/logs`, `/conf`, and `/tmp`. Setting a read-only root filesystem would mean forking those Deployments. This package does not.

## Startup order

The upstream cluster scripts exec java and do not wait. After Helm, `patch-oidc-pods.py` restarts Ignite, then rolls config, messaging, the API, and plugins, in that order. Plugins is last because it uses services from the other three, and an Ignite restart drops caches. Each consumer pod's first init container is `wait-deps.sh`. It fails closed: Ignite port 47500 within 180s, then, for messaging and the API, Deployment `takserver-config` updated and Ready within 300s. Plugins waits the same way for config, messaging, and the API. Ready means the stock readiness script passed. A listening port is not the gate. The scripts truncate `/logs/takserver-*.log` at process start so a readiness grep cannot match a line from an earlier JVM in the same container. There is no retention Deployment in this chart.

API and messaging get a TCP `startupProbe` on 8443 and 8089. The budget is 80 periods of 10s, which covers the dependency waits plus about 300s for the process. Readiness `timeoutSeconds` is 10 because those scripts call `nc` against Postgres and the default probe timeout is 1s. `pgrep -f` is not used. Messaging liveness is TCP 8089.

`TAKIgniteConfig.xml` is the pre-created ConfigMap `tak-ignite-config`. `igniteFailureDetectionTimeoutSeconds` is 30. With `clusterEnabled`, the client builds only a Kubernetes IP finder and client mode, so that attribute is not applied there. The schema has no `networkTimeout` attribute. The Ignite server config sets discovery `networkTimeout` to 15000 and `failureDetectionTimeout` to 30000. `localAddress` stays unset: that is the path that binds every interface and still advertises a real address. `0.0.0.0` is resolved as the wildcard and registered as the node address. REST is off because `OPTION_LIBS` does not include `ignite-rest-http`. `ConnectorConfiguration` has no `enabled` property, so the server XML does not set one. The Service is headless. The ServiceAccount token is mounted. RBAC can get and list pods and endpoints. Ignite work and `/tmp` are emptyDirs. The disruption budget is `floor(n/2)+1` with `n` odd (1).

`FileAuthenticator` copies the auth file to a sibling `.backup` before it replaces the file. On the API pod that copy was `AccessDeniedException: UserAuthenticationFile.xml.backup` in the working directory `/`. CoreConfig sets the file to `/opt/tak/UserAuthenticationFile.xml`. The image creates `/opt/tak` mode 0777, which is also the JVM temp directory, and copies the empty auth file there.

## Data

Postgres is the Bitnami chart the upstream TAK chart installs in the `takserver` namespace. Database `cot`, user `postgres`, Service `takserver-postgresql:5432`. The password in the overlay is the upstream example value. See [Data](data.md).

## Related docs

- [Networking](networking.md)
- [Single sign-on](sso.md)
- [Architecture decisions](../adr/0001-record-architecture-decisions.md)
- [OAuth discovery](../adr/0004-tak-oauth-uses-openid-discovery.md)
- [Data](data.md)
- [Slim core boundaries](../adr/0005-slim-core-boundaries.md)

The chart renders `postgres-configuration`, but `pg_hba.conf` and `postgres.conf` are empty because the chart has no `extras/` files for them.

The database password in the overlay is the upstream example value `postgres`. It is not a production secret. The NATS toolbox is disabled in `values/common-values.yaml`.
