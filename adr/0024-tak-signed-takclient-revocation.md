# 24. Revoke TakClient certificates through TAK's certificate table

Date: 2026-11-05

## Status

Accepted. Confirmed on a live cluster in [issue #288](https://github.com/jonathanagustin/uds-k3d-takserver/issues/288) ([run 42072025085](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/42072025085)). This record supersedes the **restart** part of [ADR 22](0022-takclient-operator.md): TakClient certificates will no longer depend on a UDS Core pod reload to take effect after revoke. The rest of ADR 22 (the resource, the Secret shape, RBAC, and the data package) stays.

## Context

[ADR 22](0022-takclient-operator.md) has the watcher sign each `TakClient` certificate with the TAK CA key, register a file user, and on delete write the serial into Secret `takserver-crl` with the UDS Core `uds.dev/pod-reload` label. TAK reads that CRL only when a TLS context is built, so UDS Core restarts the API and messaging pods. That restart drops every connected client for a few minutes. Between the delete and the restart the revoked certificate can still connect, with no groups. Issue [#288](https://github.com/jonathanagustin/uds-k3d-takserver/issues/288) asked for revocation without that restart.

TAK Server 5.7 (`5.7-RELEASE-14`) already has another path, from its source:

- `X509Authenticator` looks up the certificate's SHA-256 fingerprint in the `certificate` table when `x509tokenAuth` or `x509checkRevocation` is true. Our CoreConfig already sets `x509tokenAuth="true"`. A row with a `revocation_date` is rejected on every connection (8089 and 8443).
- `DELETE /Marti/api/certadmin/cert/revoke/{id}` sets that date and then `forceClose`s every open subscription that used the certificate.
- Rows are created only when TAK itself signs the certificate: `POST /Marti/api/tls/signClient/v2` (and the related enrollment endpoints). A certificate the watcher signs with the CA key never gets a row, so the table check cannot revoke it today.

Other options looked at for #288 and rejected:

1. **TAK plugin.** Plugins run in the plugins process and only see messages. They have no hook into the TLS trust manager or the connection lifecycle.
2. **TAK source patch** that reloads the CRL without a restart. Works for new handshakes, still needs the disconnect API for open connections, and we would carry the patch on every TAK release.
3. **TLS-terminating proxy** in front of 8089 and 8443. TAK reads the client certificate only from its own TLS session. It has no trusted-header mode. 8089 is raw TCP. A proxy that terminates TLS makes every user look like the proxy.
4. **Batching CRL writes.** Easy, but it only reduces how many restarts happen. The restart stays.

## Decision

Have TAK sign TakClient certificates, and revoke them through TAK's certificate table. Keep the CRL as a backstop that no longer restarts pods.

### Signing

- The watcher still creates the file user and keeps its password for renewal and recovery. The original decision put it in the client Secret; the security correction below stores it only in `takserver/takclient-enrollment`.
- The watcher generates a key and a CSR (`CN=<callsign>, O=TAK, OU=UDS`, matching `certificateConfig` in CoreConfig). It POSTs the CSR to `https://takserver-api:8446/Marti/api/tls/signClient/v2?clientUid=<uid>` with **Basic auth** as that file user. Basic auth, not OAuth: an OAuth enrollment stores a token on the row, and `x509tokenAuth` would then treat the client as a token user.
- TAK signs with the global `TAKServerCAConfig` lifetime (`validityDays="30"` today). `TakClient.spec.validityDays` can no longer set a per-client lifetime. The field is removed or ignored when this ships.
- The package allows ingress on **8446** to the API pod from the Pepr watcher (8443 is already allowed). No Istio change.

### Revocation

- On delete (and when Reconcile replaces a certificate):
  1. `GET /Marti/api/certadmin/cert/{hash}` with the admin certificate on 8443 to get the row id. The hash is the same SHA-256 fingerprint TAK stores (`RemoteUtil.getCertSHA256Fingerprint`, uppercase hex with colons).
  2. `DELETE /Marti/api/certadmin/cert/revoke/{id}`.
  3. Delete the file user.
- The watcher still writes the serial into Secret `takserver-crl`, but **without** the `uds.dev/pod-reload` label. The CRL then applies after any normal restart and still covers certificates issued before this change, which have no row. It is no longer what closes a live connection.
- CoreConfig keeps `x509tokenAuth="true"` and sets `x509checkRevocation="true"` explicitly.

### What does not change

- Admin and CloudTAK certificates have no row in the table. The lookup returns null, so they are unaffected. The CRL backstop still covers them after a normal restart, as today.
- The data package, the device Secret shape, RBAC for the CA key, and the `takclients` namespace stay as in ADR 22. Enrollment passwords have separate watcher-private storage.
- The watcher still does not need the CA key for TakClient signing once this ships. Reading the CA key for the CRL signature remains until the CRL is signed another way or dropped for new certificates.

### Confirmed on a cluster

Run [42072025085](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/42072025085) on free `ubuntu-latest`, against this repository's slim local install:

| Check | Result |
| --- | --- |
| File user create on 8443 | PASS |
| `signClient/v2` with Basic auth on 8446 | PASS; enroll response had no token field |
| Validity TAK assigned | ≈30.5 days (global `validityDays=30`) |
| Cert row present (`GET .../certadmin/cert/{hash}`) | PASS |
| Live 8089 connection after revoke | **closed by peer in the same second** |
| New connection with the revoked cert | handshake then closed (auth rejected) |
| Admin certificate still connects | PASS |
| `takserver-api` / `takserver-messaging` pod UIDs and restart counts | **unchanged** |

### Tests the change must keep

1. Apply a `TakClient`, connect on 8089, keep the socket open.
2. Delete the `TakClient`.
3. Assert the open socket is closed, a reconnect is refused, `/Marti/api/clientEndPoints` no longer lists the callsign, and the API and messaging pods' restart counts and start times have not changed.
4. Assert the admin certificate and CloudTAK still connect.
5. Run on amd64 and arm64.

## Consequences

- Revoking a TakClient no longer restarts TAK. Connected clients that are not revoked stay up.
- Validity is global (`TAKServerCAConfig`), not per `TakClient`. Operators who need a shorter life set the global value or delete and reissue.
- The watcher stores per-client file-user passwords in a separate, named Secret in `takserver`. Device Secret readers do not gain Basic enrollment capability.
- New Package allow: ingress on 8446 from the watcher.
- Certificates issued before the change have no table row. They stay on the CRL path until they are reissued. Reconcile already reissues when the Secret changes; a one-time reissue at upgrade covers the rest.
- An existing HTTP session on 8443 (`JSESSIONID`) may keep working until it expires, because the Spring pre-auth filter does not re-check a session that is already authenticated. Streaming on 8089 is what the trial confirmed.
- A failure from TAK's `revokeCert.sh` during the admin revoke call is expected with our JKS-only CA config. TAK catches it after the database update; it is harmless.
- No TAK source patch. The cost is depending on four documented REST endpoints (`signClient/v2`, `certadmin/cert/{hash}`, `certadmin/cert/revoke/{ids}`, user management) that ATAK enrollment and the admin UI also use.

## Implementation and upgrade behavior

The operator marks successfully enrolled certificates with
`tak.jonathanagustin.github.io/issuer: tak` on the Secret and resource. A missing
marker forces a one-time reissue. It revokes the old certificate before
publishing its replacement; a missing fingerprint or failed certadmin request
keeps Ready false, and a failed finalization retains the Secret and finalizer.
The random file-user password is written to watcher-private state before
creating the user, so retries and messaging restarts can reuse it. `spec.validityDays` is
retained for compatibility but deprecated and ignored; TAK sets the lifetime.
Renewal uses the last third of the validity on the enrolled certificate, so a
shorter global lifetime does not reissue on the next reconcile. Deleting the
Basic enrollment user is fail-closed: a failed `delete-user` keeps the device
Secret, the private enrollment entry, and the finalizer. A retry is idempotent
when the certificate row already has `revocationDate`, when delete returns
TAK's `User not found!` response, or when `list-users` succeeds and omits the
callsign. A generic HTTP 400 and an RMI lookup HTTP 404 are not absence.

A locally signed legacy certificate still uses the reload fallback. The CRL
stores `reload-at`, and subsequent CRL writes keep `uds.dev/pod-reload: true`
until all API and messaging pods have creation timestamps after that update.
Deleting a newly enrolled client cannot cancel a pending legacy reload. Once
that condition holds, or on a fresh install with no legacy revocations, CRL
writes set the reload label to false. Migration can therefore interrupt clients
once and requires importing their newly issued data packages.

`tests/takclient-revocation.py`, called by `tests/takclient.sh`, holds the target,
another TakClient and an admin stream open; it checks target disconnect and
reconnect rejection, surviving controls, actual CloudTAK status, removal from
clientEndPoints, and unchanged API/messaging pod UIDs, start times and restart
counts. Production dual-architecture cluster acceptance remains required before
this implementation is released; the historical trial above is not its result.

The CRL is still cached by Java. Its periodic refresh near `nextUpdate` (and
replacement after a CA change) requests a reload so an old cached CRL cannot
expire and reject every client. That maintenance reload is separate from
per-client certificate-table revocation; it is not removed by this change.

## Security correction: enrollment capability is not device material

[Issue 345](https://github.com/jonathanagustin/uds-k3d-takserver/issues/345) records
a flaw in the original storage decision. A device Secret reader given the
reusable Basic password could enroll extra certificate-table rows that a revoke
of the operator's fingerprint would miss. The released locally signed path did
not expose this password; the initial draft implementation did and must not be
released in that form.

Passwords now live only in Secret `takserver/takclient-enrollment`, with one
entry per TakClient name. Watcher RBAC grants named `get` and `patch`; its
existing Secret-create grant is sufficient. Neither admission accounts nor
accounts limited to reading the `takclients` namespace gain access. The
operator never copies that password into device Secrets or data packages.
There are no cross-namespace owner references.

A process-local lock serializes writes so one client's update or cleanup does
not drop another's entry (the watcher runs one replica). The credential is saved
before creating the TAK user. Losing that private entry forces revocation and
reissue with a new user password; a device-provided field is not trusted as
private state. Finalization removes the entry only after successful revoke and
client Secret cleanup. If revoke fails, both the credential and finalizer stay.
The containing private Secret may remain empty and is included in the TAK
namespace backup.

Enrollment validates both certificate date bounds against one fresh clock sample
after the response arrives. Reusing reconcile start time could reject a newly
valid certificate or accept one that expired in flight; advancing-clock tests
cover both cases ([issue 350](https://github.com/jonathanagustin/uds-k3d-takserver/issues/350)).
