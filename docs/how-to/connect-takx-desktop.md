# Prepare a TAKX desktop connection

Prepare a dedicated desktop-client identity and a repeatable compatibility check.
TAKX interoperability with this deployment is **not yet verified**. This guide
records the setup to test; it does not claim a working installer or import flow.

## What you'll accomplish

Provision a `TakClient`, prepare its client certificate and trust material, and
check TAKX streaming, HTTPS services and group isolation against CloudTAK.
Record the results in [the compatibility issue](https://github.com/jonathanagustin/uds-takserver/issues/374).

## Prerequisites

- A working [TAK deployment](../../README.md#install), the UDS CLI, Python 3,
  and permission to create `TakClient` resources and read their device Secrets.
- An approved TAKX installation on a test workstation. Record its version,
  source, operating system and plugins. This repository supplies no installer.
  The original upstream build requires TAK.gov Artifactory credentials; follow the
  [upstream instructions](https://github.com/TAK-Product-Center/TAKX#build-and-development-instructions).
- Workstation DNS and routes to the passthrough gateway, and a CloudTAK test user
  in `Operators`. Use synthetic markers and a separate unrelated group for tests.

## Current build status

Public-source work compiles Kernel Java foundations and a WorldWind project
variant. Separate Linux amd64 component checks cover Draco, LAS, Assimp and
historical PROJ; they do not supply a linked native Kernel, launchable TAKX
desktop or Kasm session. See the [component and client checkpoint](../../takx/CLIENT-CHECKPOINT.md#native-component-checkpoints).

Platform compiler probes still stop at missing native texture-rendering APIs;
5.8 also has contour and vehicle-model gaps. [Native rendering](https://github.com/jonathanagustin/uds-takserver/issues/424)
and live client/server interoperability remain unverified. Use an approved,
working installation for the connection checks below.

## Before you begin

TAKX is a desktop client. Its client certificate is separate from CloudTAK's
Keycloak browser session. Use a dedicated identity, not the TAK admin certificate
or a shared device certificate.

For the configuration below, replace `<domain>` with the deployment domain:

| Purpose | External address | Required behavior |
| --- | --- | --- |
| Streaming | `takserver-stream.<domain>:8089` | End-to-end mutual TLS to TAK messaging |
| HTTPS API, missions and files | `https://takserver-api.<domain>/` | Port 443 with TLS SNI, forwarded to TAK's client-certificate connector on 8443 |
| Enrollment, if separately tested | `takserver.<domain>:8446` | A different connector; not needed for this pre-provisioned certificate flow |

These names must resolve to the **passthrough** load balancer externally. On k3d,
8446 and 8089 are not published to the host by default; its host port 443 serves
the tenant gateway. Arrange reachable passthrough routes first. See
[Standard TAK ports](../networking.md#standard-tak-ports).

Streaming success does not prove HTTPS access. The inspected TAKX source defaults
the secure server API port to 8443. Record the HTTPS host and port TAKX actually
requests; do not assume it uses the package's split-host 443 route.
If the build requires a different API address, stop that acceptance check until
an appropriate route or client configuration is documented. Check DNS names
against the server certificate, and keep certificate validation enabled.

## Steps

1. Create a dedicated identity in the group used by the CloudTAK test user:

   ```bash title="Provision the desktop test identity"
   uds zarf tools kubectl apply -f - <<'YAML'
   apiVersion: tak.jonathanagustin.github.io/v1alpha1
   kind: TakClient
   metadata:
     name: takx-test
     namespace: takclients
   spec:
     callsign: takx-test
     groups:
       - Operators
   YAML
   uds zarf tools kubectl wait takclient/takx-test -n takclients \
     --for=condition=Ready --timeout=180s
   ```

2. Export only that identity's material to a private directory. This reads the
   Secret into memory and writes files without displaying keys or passwords:

   ```bash title="Export private client files"
   umask 077
   export TAKX_CREDENTIAL_DIR="$(mktemp -d)"
   python3 - <<'PY'
   import base64
   import io
   import json
   import os
   from pathlib import Path
   import subprocess
   import zipfile

   secret = json.loads(subprocess.check_output([
       "uds", "zarf", "tools", "kubectl", "get", "secret", "takx-test",
       "-n", "takclients", "-o", "json",
   ]))["data"]
   output = Path(os.environ["TAKX_CREDENTIAL_DIR"])
   for key in ("client.pem", "client.key", "ca.pem", "password"):
       name = "password.txt" if key == "password" else key
       (output / name).write_bytes(base64.b64decode(secret[key]))
   with zipfile.ZipFile(io.BytesIO(base64.b64decode(secret["package.zip"]))) as package:
       (output / "client.p12").write_bytes(package.read("certs/takx-test.p12"))
       (output / "truststore.p12").write_bytes(package.read("certs/truststore.p12"))
   PY
   ```

   Transfer the directory through your approved secure channel. Do not commit it
   or attach it to an issue. `password.txt` protects the two PKCS#12 files; it is
   not a Keycloak or TAK enrollment password. Do not export the watcher-private
   `takserver/takclient-enrollment` Secret.

3. In your installed TAKX build, configure a certificate-based SSL connection to
   the streaming address. Use `client.p12` as the client credential and
   `truststore.p12` as the CA store, with the exported package password. Keep
   server trust enabled, and require hostname validation as well. The original
   public CommonCommo 1.17.2 candidate lacks server hostname verification. The
   [project transport profile](../../takx/TLS.md) now adds configured DNS/IP SAN
   validation and DNS SNI, with real loopback acceptance and a separately pinned
   curl shutdown fix. It rejects CN-only certificates. This does not establish
   that an installed TAKX build contains these patches or passes TAK Server
   interoperability. Record its actual library identity, behavior and import
   steps; verify trusted-CA wrong-name rejection in the installed client.

   The inspected upstream connection editor accepts `.p12` files and defaults to
   streaming port 8089. Its source also has an ATAK-style preference importer,
   but importing this repository's whole `package.zip` into TAKX has not been
   demonstrated. The PEM files are available for diagnostics; their acceptance
   by TAKX's certificate chooser is not established.

4. Run the manual checks below. After credential renewal or migration, export
   the updated Secret and re-import it; verify the old credential no longer
   works. To retire the test identity, delete its `TakClient`:

   ```bash title="Revoke the test identity"
   uds zarf tools kubectl delete takclient takx-test -n takclients
   ```

   The controller revokes the issued certificate before deleting its device
   Secret. Confirm disconnection and rejected reconnects. A revocation failure
   retains the finalizer for retry; do not remove it to make the test pass.

## Verification

Record **Pass**, **Fail** or **Not run**, with evidence, for every row. No live
TAKX result is supplied by this guide. A missing plugin or unsupported endpoint
is a limitation to record, not a passing check.

| Check | Evidence to retain |
| --- | --- |
| Installation and identity | TAKX version/commit or installer checksum, OS/architecture, plugin versions; TAK Server, package and Core versions; test date |
| Streaming TLS | Actual host/port, successful connection with the dedicated certificate, server trust and hostname validation enabled |
| Negative trust | An unrelated CA is rejected without disabling certificate validation |
| Server identity | A certificate from a trusted CA for a different hostname is rejected |
| HTTPS reachability | The host/port TAKX requests for missions/files and the result, tested separately from streaming |
| Shared group | A clearly labeled synthetic marker travels TAKX to CloudTAK and back within `Operators` |
| Group isolation | A user in the unrelated group cannot see those test events or restricted content |
| Mission and package transfer | Mission synchronization and a harmless data package in both directions, or the exact plugin/version limitation |
| Renewal | Updated credential imports and reconnects; old credential is rejected |
| Revocation | Deleting the test identity disconnects it and prevents reconnecting |

Keep only sanitized screenshots, timestamps, public certificate fingerprints
and short error summaries. Remove local private files when the test is finished.
Capture a demo only after these checks pass, with no operational location data
or credential dialogs in view.

## Troubleshooting

### Streaming connects but missions or files fail

**Problem:** Only one protocol path works.

**Symptom:** TAKX appears online but mission synchronization or transfers fail.

**Solution:** Inspect the actual HTTPS destination and check DNS, TLS SNI, client
certificate trust and port exposure separately. The streaming host on 8089 does
not establish compatibility with the API host on 443.

### The credential is rejected or no peers appear

**Problem:** Certificate import, trust or group membership is incomplete.

**Symptom:** TLS fails, or a connected client sees no CloudTAK test user.

**Solution:** Check the `TakClient` Ready condition, certificate expiry, the
matching PKCS#12 password and the file user's group assignment. Re-export after
rotation. Use the version-specific TAKX import procedure; do not substitute
CloudTAK's browser password or the server admin certificate.

## Related documentation

- [Device certificate provisioning](../atak-device.md#provisioning-device-certificates)
- [Networking and gateway routes](../networking.md)
- [TAK-issued client revocation](../../adr/0024-tak-signed-takclient-revocation.md)
- [TAKX connection editor inspected at af54a3e](https://github.com/TAK-Product-Center/TAKX/blob/af54a3e1fe8796b6e109e2e5925dbef524ea7e31/Client/src/main/java/gov/takx/core/view/gui/takserver/TakServerConnectionDetailsPanel.java)
- [TAKX data-package connection importer](https://github.com/TAK-Product-Center/TAKX/blob/af54a3e1fe8796b6e109e2e5925dbef524ea7e31/Platform/src/main/java/gov/tak/platform/datapackage/TakServerConnectionImporter.java)
- [TAKX integration scope and remaining acceptance](https://github.com/jonathanagustin/uds-takserver/issues/372)
