# 22. Issue TAK client certificates from a TakClient resource

Date: 2026-11-03

## Status

Accepted. The **restart-on-revoke** path in Delete and Consequences is superseded by [ADR 24](0024-tak-signed-takclient-revocation.md). The resource, Secret shape, RBAC, and data package in this record still apply.

## Context

A TAK client that uses a certificate needs four things: a key and a certificate signed by the TAK CA, a TAK file user that maps the certificate to its groups, the CA in a truststore, and a connection data package that points at `takserver-stream.<domain>:8089`. Today the ATAK e2e job does all four by hand on the runner ([ADR 14](0014-atak-test-device-in-kubevirt.md), `atak/ci/e2e.sh`): `openssl` signs the certificate, `kubectl exec` runs `UserManager.jar certmod -g <group>` in the messaging pod, and a script zips the data package. An operator who wants a device does the same steps from [the device docs](../docs/atak-device.md#provisioning-device-certificates). Issue #36 asks for a `TakClient` custom resource that the `takserver-oidc` Pepr module turns into a certificate, a Secret, and a data package.

What is already true:

- The CA key is not in ConfigMap `cert-migration`. Since [ADR 2](0002-generate-certificates-at-deploy-time.md), `ca-do-not-share.key` is in Secret `takserver/takserver-ca-key`, and the cert Job removes it from the ConfigMap on upgrade. The key is encrypted with `CAPASS` from Secret `takserver-keystore`. The ConfigMap still holds `ca.pem`, which is public. No change to where the key is stored is needed.
- The chart `pepr build` writes runs the module's admission pods and its watcher as one ServiceAccount, `pepr-c72fcf944a4f43bbb386d22371aa640f`. `pepr/scripts/rbac-scope.ts` already moves the watched objects to named Roles.
- The watcher already reads Secret `takserver-certs` (`admin.pem`, `admin.key`) and Secret `takserver-keystore` to build CloudTAK's admin Secret.

What TAK Server 5.7 (`5.7-RELEASE-14`, the upstream tag this repository builds) supports for revocation, from its source:

- A CRL file on the TLS settings. `CoreConfig.xsd` allows `<crl _name crlFile>` inside `<security><tls>`. `SSLConfig.java` reads each `crlFile` into the PKIX trust manager for the streaming ports, and `ServerConfiguration.java` passes the first one to Tomcat (`setCertificateRevocationListFile`) for 8443 and the other HTTPS connectors. Both read the file when the TLS context is built. `SSLConfig.getInstance` caches that context for the life of the process, and nothing watches the file. A new CRL therefore applies only after the messaging and API pods restart. A connection that is already open is not closed. `NioNettyHandlerBase` logs `Connection rejected for revoked client certificate` when a revoked certificate tries to connect.
- `revokeCert.sh` in `src/takserver-core/scripts/certs`, which runs `openssl ca -revoke` and `openssl ca -gencrl`. `makeRootCa.sh` already writes an empty `ca.crl` with `default_crl_days = 730` from `config.cfg`.
- `<auth x509checkRevocation>`. `X509Authenticator` then rejects a certificate whose row in the `certificate` table has a `revocation_date`. That table only holds certificates TAK issued itself through enrollment (`TakCertRepository`, `/certadmin/cert/revoke/{ids}`). A certificate signed outside TAK has no row, so this check does not apply to it.
- Removing the file user (`DELETE /user-management/api/delete-user/{username}`, or `certmod -D`). This does not stop the certificate. `X509Authenticator` matches a certificate to a file user by SHA-256 fingerprint or by CN. A trusted certificate with no file user still connects, in the anonymous group only.
- There is no OCSP responder in this deployment. `enableOCSP` exists in the schema, but nothing here would answer it.

## Decision

### The resource

- `TakClient`, group `tak.jonathanagustin.github.io`, version `v1alpha1`, namespaced. The TypeScript type is in `pepr/api/` and the CRD is generated with `npx pepr crd generate`. The generated CRD ships in the module chart. The group is a domain this repository's owner controls, and `v1alpha1` leaves room to change the schema.
- `spec.callsign`: the certificate CN and the TAK file user name. It must pass TAK's username rule.
- `spec.groups`: one or more TAK groups, for example `["Operators"]`.
- `spec.validityDays`: certificate lifetime, default 30, maximum 365.
- `status.conditions`: `Ready`, with a reason when it is false (`InvalidSpec`, `NoDomain`, `WaitingForCa`, `WaitingForAdmin`, `TakUnavailable`) and `Issued` when it is true. The condition has `observedGeneration`. The Pepr 2.0.7 CRD generator writes only `conditions` under `status`, so the serial number, the SHA-256 fingerprint, and `notAfter` are annotations (`tak.jonathanagustin.github.io/serial`, `/fingerprint`, `/not-after`) on the `TakClient` and on its Secret.
- A `TakClient` is reconciled only in namespace `takclients`, which the module chart creates. Its Secret has the same name, in the same namespace, with `client.pem`, `client.key`, `ca.pem`, `package.zip` (the data package), and `password` (the PKCS#12 password in the package). Only these Secrets live in `takclients`, so the watcher's Secret verbs there need no names. A Role cannot pin Secret `create` to a name, and this keeps that grant away from namespaces with other Secrets. A device in another namespace, such as the ATAK test VM in `atak`, gets a copy made by whoever deploys it.

### Where signing happens

- The watcher signs. It reads `ca.pem` from ConfigMap `cert-migration`, `ca-do-not-share.key` from Secret `takserver-ca-key`, and `CAPASS` from Secret `takserver-keystore`. It decrypts the CA key in memory with Node's `crypto`, generates an RSA 2048 client key, and signs a certificate with `extendedKeyUsage = clientAuth` and a random 128-bit serial. The CA key is never written to disk, a log, a status field, or another object.
- The client key exists only in the output Secret. The image has no key, and git has no key. The existing gitleaks rule and `*.key` ignore stay.
- The alternative was a Job that runs `makeCert.sh client` in the `takserver-config` image. It would keep the CA key out of the watcher, but the watcher would need Job `create` and would still have to read the Job's output, which holds the client key. Signing in the watcher is fewer moving parts and the same set of readers.

### Who can read the CA key

- The watcher runs as its own ServiceAccount, `pepr-<uuid>-watcher`. The admission pods keep `pepr-<uuid>`. `pepr/scripts/rbac-scope.ts` adds the account and points the watcher Deployment at it.
- Every Secret rule and every `TakClient` rule is in a Role or ClusterRole named `pepr-<uuid>-watcher…`, bound only to the watcher account. That includes `get`, `list`, and `watch` on Secret `takserver/takserver-ca-key`, by name. The other rules (ConfigMaps, Deployments, pods, Services, and the rest) are bound to both accounts.
- The admission pods read only ConfigMap `core-config`, so they can read no Secret at all. `tests/takclient.sh` checks this with `kubectl auth can-i` against both accounts.
- Before this change, only the cert Job and cluster administrators could read the CA key.
- Creating a `TakClient` is the same as being given a certificate for any TAK group. The CRD has no `aggregate-to-edit` or `aggregate-to-admin` label, so only cluster administrators can create one until someone grants it on purpose.

### Registering the client in TAK

- The watcher calls TAK's admin API on `takserver-api:8443` with the admin certificate it already reads: `POST /user-management/api/new-user` with the callsign, the groups, and a random password that nobody keeps (TAK requires one). `X509Authenticator` then maps the certificate to that user by CN.
- `UserAuthenticationFile.xml` is not on a volume, so a messaging restart loses the user. The watcher already watches `takserver-messaging` for the startup order. When it becomes Available, the watcher registers every `TakClient` again. A `TakClient` that is not `Ready` because the CA, the admin certificate, or TAK is not ready yet is tried again every minute: the watcher writes annotation `tak.jonathanagustin.github.io/reconcile-retry`, which sends another update.
- The takserver Package allows ingress to `takserver-api` on 8443 from the watcher pods in `pepr-system` (`app: pepr-<uuid>-watcher`), with the watcher's ServiceAccount (`pepr-<uuid>-watcher`) as `remoteServiceAccount`. `pepr-system` is ambient, like `takserver`.
- The TAK API's server certificate is not issued for the Service name, so the watcher checks the chain against the TAK CA and skips the host name check.

### Delete

- A Pepr `Finalize` on `TakClient`:
  1. Deletes the TAK file user, so a new connection gets no groups.
  2. Adds the serial to the CRL and writes it to Secret `takserver/takserver-crl`, signed by the TAK CA, with a `nextUpdate` 730 days out, as TAK's own `config.cfg` sets.
  3. Deletes the client's Secret.
- Pepr adds its finalizer in the mutating webhook. `finalize-chart.mjs` narrows that webhook to namespace `takserver` and, with match conditions, to the TAK objects (see `webhook-scope.ts`). `splitTakClientWebhook` moves the `takclients` rule to a second webhook entry that matches only namespace `takclients`, with the same path, CA bundle, timeout, and failure policy and without those match conditions.
- If finalize cannot finish (the CA is not readable), it keeps the finalizer and writes an annotation 30 seconds later, which runs it again.
- A certificate that Reconcile replaces (the Secret was deleted, the callsign changed, or a third of the lifetime is left) is added to the CRL too.
- The render capability mounts `takserver-crl` into the messaging and API pods, and CoreConfig gets `<crl _name="tak-ca" crlFile="certs/crl/ca.crl"/>` in `<security><tls>`. The Secret has the UDS Core `uds.dev/pod-reload` label, so UDS Core restarts those pods when the CRL changes and TAK starts rejecting the certificate. Between the delete and the restart, the certificate can still connect, with no groups.
- The watcher writes an empty CRL when the Secret is missing, so TAK always has a file to load. The CRL volume is not optional, so a TAK pod waits for it. The watcher checks the CRL when the CA material changes, on each `TakClient` reconcile, and once a day. It writes a new one with the same entries when `nextUpdate` is less than 60 days away, and drops entries for certificates that have expired. Java rejects every client certificate if the CRL has expired. If the CA changes, it writes an empty CRL signed by the new CA.
- Finalize removes the finalizer only after the CRL Secret is written. If TAK is not reachable, the user is left behind and the watcher logs it. The revocation restart starts messaging with no file users, so the user is gone after it. The CRL is what stops the certificate.

### Tests

- Unit tests in `pepr/capabilities/` keep the 100% line, branch, and function gate. They cover signing against a CA generated in the test, the data package contents, the status conditions, and the finalizer order.
- A cluster test applies a `TakClient` for callsign `takclient-test`, waits for `Ready`, connects on 8089 with the Secret's certificate, and checks `/Marti/api/clientEndPoints` for the callsign. It then deletes the resource, waits for the API and messaging pods to restart, and checks that the handshake with that certificate fails. It runs on amd64 and arm64.
- The ATAK e2e job applies a `TakClient` for `atak-device` and copies its data package into the `atak` namespace, in place of the `openssl` and `certmod` steps.
- `tests/takclient.sh` is task `test:takclient`, the last step of `test:all`.

## Consequences

- ~~Revocation needs a restart of the TAK API and messaging pods.~~ Superseded by [ADR 24](0024-tak-signed-takclient-revocation.md): TakClient certificates are signed by TAK and revoked through the certadmin API, so a live connection closes without a pod restart. The CRL remains as a backstop without `uds.dev/pod-reload`.
- Adding a CRL to `<security><tls>` turns on CRL checks for every certificate the TAK CA signed, including the admin certificate and CloudTAK's. An expired or unreadable CRL would reject all of them. The watcher keeps it current, and `tests/` checks that the CRL loads.
- The module's watcher can now read the TAK CA key. A compromise of the watcher pod is a compromise of the CA. The admission pods cannot read it. Before this change, the cert Job was the only workload with that access.
- Deleting the `takclients` namespace, or uninstalling the module chart, deletes every `TakClient` Secret. If the watcher is not running then, the finalizers hold the delete until it is.
- The watcher makes HTTPS calls to TAK, which it did not do before. That is a new network rule and a new failure mode, reported in the `Ready` condition.
- Nothing schedules a renewal. A reconcile issues a new certificate when less than a third of its lifetime is left, but a reconcile runs only when the `TakClient` changes or the watcher starts. Annotation `tak.jonathanagustin.github.io/not-after` shows the expiry. Scheduled renewal is a later change.
- Certificates that TAK issues through enrollment on 8446 are not affected. They are still revoked through TAK's own certificate table.
