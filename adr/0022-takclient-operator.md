# 22. Issue TAK client certificates from a TakClient resource

Date: 2026-11-03

## Status

Proposed

## Context

A TAK client that uses a certificate needs four things: a key and a certificate signed by the TAK CA, a TAK file user that maps the certificate to its groups, the CA in a truststore, and a connection data package that points at `takserver-stream.<domain>:8089`. Today the ATAK e2e job does all four by hand on the runner ([ADR 14](0014-atak-test-device-in-kubevirt.md), `atak/ci/e2e.sh`): `openssl` signs the certificate, `kubectl exec` runs `UserManager.jar certmod -g <group>` in the messaging pod, and a script zips the data package. An operator who wants a device does the same steps from [the device docs](../docs/atak-device.md#provisioning-device-certificates). Issue #36 asks for a `TakClient` custom resource that the `takserver-oidc` Pepr module turns into a certificate, a Secret, and a data package.

What is already true:

- The CA key is not in ConfigMap `cert-migration`. Since [ADR 2](0002-generate-certificates-at-deploy-time.md), `ca-do-not-share.key` is in Secret `takserver/takserver-ca-key`, and the cert Job removes it from the ConfigMap on upgrade. The key is encrypted with `CAPASS` from Secret `takserver-keystore`. The ConfigMap still holds `ca.pem`, which is public. No change to where the key is stored is needed.
- The module's admission pods and its watcher use one ServiceAccount, `c72fcf944a4f43bbb386d22371aa640f`, from the chart `pepr build` writes. `pepr/scripts/rbac-scope.ts` already moves the watched objects to named Roles.
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
- `status.conditions`: `Ready`, with a reason when it is false. `status` also has the serial number, the SHA-256 fingerprint, `notAfter`, the Secret name, and `observedGeneration`.
- A `TakClient` is reconciled only in namespace `takserver`. Its Secret is written there. A device in another namespace, such as the ATAK test VM in `atak`, gets a copy made by whoever deploys it. This keeps Secret `create`, which a Role cannot pin to a name, inside the one namespace the module already writes to.

### Where signing happens

- The watcher signs. It reads `ca.pem` from ConfigMap `cert-migration`, `ca-do-not-share.key` from Secret `takserver-ca-key`, and `CAPASS` from Secret `takserver-keystore`. It decrypts the CA key in memory with Node's `crypto`, generates an RSA 2048 client key, and signs a certificate with `extendedKeyUsage = clientAuth` and a random 128-bit serial. The CA key is never written to disk, a log, a status field, or another object.
- The client key exists only in the output Secret. The image has no key, and git has no key. The existing gitleaks rule and `*.key` ignore stay.
- The alternative was a Job that runs `makeCert.sh client` in the `takserver-config` image. It would keep the CA key out of the watcher, but the watcher would need Job `create` and would still have to read the Job's output, which holds the client key. Signing in the watcher is fewer moving parts and the same set of readers.

### Who can read the CA key

- Only the watcher. `finalize-chart.mjs` gives the watcher Deployment its own ServiceAccount, and the Role that grants `get` on Secret `takserver-ca-key` (by name) binds only that account. The admission pods keep the shared account and cannot read the key. Today only the cert Job and cluster administrators can read it.
- Creating a `TakClient` is the same as being given a certificate for any TAK group. The CRD has no `aggregate-to-edit` or `aggregate-to-admin` label, so only cluster administrators can create one until someone grants it on purpose.

### Registering the client in TAK

- The watcher calls TAK's admin API on `takserver-api:8443` with the admin certificate it already reads: `POST /user-management/api/new-user` with the callsign, the groups, and a random password that nobody keeps (TAK requires one). `X509Authenticator` then maps the certificate to that user by CN.
- `UserAuthenticationFile.xml` is not on a volume, so a messaging restart loses the user. The watcher already watches `takserver-messaging` for the startup order. When it becomes Available, the watcher registers every `TakClient` again.
- The takserver Package allows ingress to `takserver-api` on 8443 from the watcher pods in `pepr-system`.

### Delete

- A Pepr `Finalize` on `TakClient`:
  1. Deletes the TAK file user, so a new connection gets no groups.
  2. Adds the serial to the CRL and writes it to Secret `takserver/takserver-crl`, signed by the TAK CA, with a `nextUpdate` 730 days out, as TAK's own `config.cfg` sets.
  3. Deletes the client's Secret.
- The render capability mounts `takserver-crl` into the messaging and API pods, and CoreConfig gets `<crl _name="tak-ca" crlFile="certs/crl/ca.crl"/>` in `<security><tls>`. The Secret has the UDS Core `uds.dev/pod-reload` label, so UDS Core restarts those pods when the CRL changes and TAK starts rejecting the certificate. Between the delete and the restart, the certificate can still connect, with no groups.
- On first start, the watcher writes an empty CRL if the Secret is missing, so TAK always has a file to load. It writes a new CRL with the same entries when `nextUpdate` is less than 60 days away. Java rejects every client certificate if the CRL has expired.
- Finalize removes the finalizer only after the CRL Secret is written. If TAK is not reachable, the user deletion is retried on the next messaging Available event. The CRL is what stops the certificate.

### Tests

- Unit tests in `pepr/capabilities/` keep the 100% line, branch, and function gate. They cover signing against a CA generated in the test, the data package contents, the status conditions, and the finalizer order.
- A cluster test applies a `TakClient` for callsign `takclient-test`, waits for `Ready`, connects on 8089 with the Secret's certificate, and checks `/Marti/api/clientEndPoints` for the callsign. It then deletes the resource, waits for the API and messaging pods to restart, and checks that the handshake with that certificate fails. It runs on amd64 and arm64.
- The ATAK e2e job applies a `TakClient` for `atak-device` and copies its data package into the `atak` namespace, in place of the `openssl` and `certmod` steps.

## Consequences

- Revocation needs a restart of the API and messaging pods. That drops every connected client for the length of the restart. Deleting many clients at once causes one restart per CRL write, unless the writes are batched. A short `validityDays` is still the main control, as [ADR 14](0014-atak-test-device-in-kubevirt.md) already says.
- Adding a CRL to `<security><tls>` turns on CRL checks for every certificate the TAK CA signed, including the admin certificate and CloudTAK's. An expired or unreadable CRL would reject all of them. The watcher keeps it current, and `tests/` checks that the CRL loads.
- The watcher can now read the TAK CA key. A compromise of the watcher pod is a compromise of the CA. Before this change, the cert Job was the only workload with that access.
- The watcher makes HTTPS calls to TAK, which it did not do before. That is a new network rule and a new failure mode, reported in the `Ready` condition.
- Certificates are not renewed automatically. `status.notAfter` shows the expiry. Renewal is a later change.
- Certificates that TAK issues through enrollment on 8446 are not affected. They are still revoked through TAK's own certificate table.
