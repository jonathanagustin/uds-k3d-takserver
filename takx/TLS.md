# Actual CommonCommo loopback mutual TLS

This standalone opt-in smoke uses the actual source-built public CommonCommo
1.17.2 Java/JNI/core implementation and locked streaming-contact patch. It does
not invoke a native build, change the build recipe or modify cache metadata.
No private SDK or unofficial binary is downloaded. Existing crypto and TCP/UDP
routing smokes run first and remain unchanged.

## Run against trusted existing outputs

Use trusted JDK 17 on JAVA_HOME, OpenSSL 3 on PATH, and the existing materialized
locked public archives. Set the prefix and its actual compiled source directory:

```bash
export JAVA_HOME=/path/to/trusted/jdk17
python3 takx/test-tls.py \
  --source /path/to/pinned/atak-civ \
  --prefix /path/to/source-built/commoncommo-prefix \
  --compiled-source /path/to/source-built/commoncommo-prefix/commoncommo \
  --report /path/to/new/mtls-report.json
```

The runner verifies the official Git revision, clean consumed upstream files,
source-archive bytes and locked patch hashes. It exports and applies the exact
patch in temporary storage and compares every tracked source file against the
supplied compiled source tree. It records actual JAR/JNI/static/TLS library hashes
and the resolved native runtime dependency closure. Missing libraries or changed
artifacts stop the test. These checks assume the supplied local outputs came
from the reviewed source build; source comparison and hashes do not manufacture
a missing clean-build attestation or authenticate arbitrary user-supplied code.

The accepted local incremental prefix was `/workspace/scratch/commo-route-native`,
which predates completed-cache metadata for the patched recipe. All 349 source
files matched the official `9f6893dd657feacc35ec5de03dad721c2e44170e` export plus
locked patch. No completed build-state was written or relabeled. A fresh full
recipe/cache acceptance remains separate from this incremental source/runtime
proof. The earlier unpatched clean prefix is not silently substituted for it.

The runner compiles the three real smoke classes into a new temporary directory.
It generates two independent ephemeral RSA CAs and signed server/client
certificates using the installed OpenSSL executable. Server/client identities
have appropriate EKUs; server SAN includes 127.0.0.1 and localhost. PKCS12 identity
and trust material, keys and passwords exist only in restricted temporary
storage/environment and are removed on success or failure. Passwords are not
command arguments or report fields. The report must be new; command failures
use static bounded messages rather than command/output serialization.

## Exercised behavior

- A real JDK SSLServerSocket requires a client certificate and authenticates
  the exact generated leaf. Its standard trust manager accepts the proper CA.
- Native CommonCommo validates the server's trusted chain. CoT sent by that
  server creates a real native-discovered contact; sendCoT to that contact
  traverses the authenticated TLS stream and arrives at the server.
- With another server CA trust store, native CommonCommo must report
  CONN_SSL_PEER_CERT_NOT_TRUSTED. The interface must never become Up and no
  application CoT may arrive, including after an attempted broadcast.
- With a server trust store that rejects the client CA, the required-client-auth
  server must reject the handshake and accept no application data despite an
  attempted broadcast.
- Real interfaces are removed, the peer socket threads are joined and native
  Commo shuts down. Individual socket waits and the whole JVM are bounded.

## Explicit security and compatibility boundary

The pinned official
[streaming TLS source](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/commoncommo/core/impl/streamingsocketmanagement.cpp#L1966) performs
its own SSLCertChecker/X509_verify_cert chain check after SSL_connect. It
**intentionally does not compare CN/SAN to hostname**, as its source comment
states. The smoke adds no bypass or custom permissive trust manager and tests
wrong-chain rejection, but it cannot claim hostname validation. The loopback
SAN is valid; that alone does not prove the native client checks it. Resolving
that upstream transport policy is separate work requiring its own reviewed
implementation and mismatch tests.

This is not TAK Server interoperability, certificate enrollment, a full TLS
policy audit, revocation testing, hermetic packaging, map/GL acceptance or a
complete TAKX build. Both official client candidates remain unaccepted.

Fast guard tests do not load JNI or open sockets:

```bash
python3 -B -m unittest discover -s takx -p test_tls_guards.py -v
```
