# Actual CommonCommo loopback mutual TLS

This standalone opt-in smoke uses the actual source-built public CommonCommo
1.17.2 Java/JNI/core implementation and locked streaming-contact and server-identity
patches. It does
not invoke a native build, change the build recipe or modify cache metadata.
No private SDK or unofficial binary is downloaded. Existing crypto and TCP/UDP
routing smokes remain unchanged; the read-only signal regression also runs.

## Run against trusted existing outputs

Use trusted JDK 17 on JAVA_HOME, OpenSSL 3 on PATH, and the existing materialized
locked public archives. The prefix must contain the patched curl source as well
as its built static library. Set the prefix and its actual compiled source directory:

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
patches in temporary storage and compares every tracked source file against the
supplied compiled source tree. It records actual JAR/JNI/static/TLS library hashes
and the resolved native runtime dependency closure. Missing libraries or changed
artifacts stop the test. These checks assume the supplied local outputs came
from the reviewed source build; source comparison and hashes do not manufacture
a missing clean-build attestation or authenticate arbitrary user-supplied code.

The earlier `/workspace/scratch/commo-route-native` checkpoint verified CA chains
with the routing patch only. The new isolated hostname-proof prefix rebuilds
all CommonCommo core and JNI objects using the same verified dependency inputs
and unchanged Java API JAR. Its source must match official revision
`9f6893dd657feacc35ec5de03dad721c2e44170e` plus both ordered patches. No completed
build-state is written or relabeled. A fresh full recipe/cache acceptance
remains separate from this source/runtime proof. The earlier checkpoint is
preserved and cannot pass the new exact staged-source check.

The runner compiles the four real smoke classes into a new temporary directory.
It generates two independent ephemeral RSA CAs and signed server/client
certificates using the installed OpenSSL executable. Server/client identities
have appropriate EKUs. The positive server SAN includes 127.0.0.1 and localhost;
negative leaves use the same trusted CA with deliberately incorrect DNS/IP SANs,
a DNS-typed numeric address, or only a matching CN. PKCS12 identity
and trust material, keys and passwords exist only in restricted temporary
storage/environment and are removed on success or failure. Passwords are not
command arguments or report fields. The report must be new; command failures
use static bounded messages rather than command/output serialization.

## Exercised behavior

- A real server-mode JDK SSLSocket requires a client certificate and authenticates
  the exact generated leaf with its standard trust manager. The fixture owns
  its underlying loopback TCP socket; cleanup closes that transport before the
  JSSE wrapper, avoiding another close-notify write to an already rejected peer.
- Native CommonCommo checks the server CA chain and configured endpoint identity.
  Both `localhost` and `127.0.0.1` carry authentication and received/discovered/
  routed CoT. The peer observes exactly `localhost` as DNS SNI and no SNI for IP.
- A valid-CA certificate with a wrong DNS SAN is rejected even though its IP SAN
  matches the resolved address and its CN matches the caller's DNS name. A
  wrong IP SAN, a DNS-typed numeric IP and a CN-only DNS certificate are rejected.
  Each must produce CONN_SSL_PEER_CERT_NOT_TRUSTED before Up; no authentication
  document or CoT may arrive, including after an attempted broadcast.
- A wrong server-CA trust store still produces native certificate rejection.
  A required-client-auth server with the wrong client-CA trust store still
  rejects the handshake and receives no application data. Explicit JNI SSL
  interface creation without a client certificate is rejected before connection.
- Real interfaces are removed, peer threads are joined and Commo shuts down.
  Individual socket waits and each JVM invocation have finite deadlines.

## Source contract and identity policy

The pinned official
[streaming TLS source](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/commoncommo/core/impl/streamingsocketmanagement.cpp#L1966)
performs its own SSLCertChecker/X509_verify_cert chain check after SSL_connect.
Patch `0101-commoncommo-stream-server-identity.patch` preserves that check and
client-certificate handling. It captures the original caller-supplied endpoint
and whether it was parsed as an IP before DNS resolution, retains this immutable
identity across retries, and supplies DNS SNI before SSL_connect.

After chain verification it requires OpenSSL `X509_check_host` for DNS or
`X509_check_ip_asc` for a literal IP to return exactly 1, before the interface
can become Up or enqueue authentication. Failures, malformed names and internal
matching errors fail closed. DNS uses `X509_CHECK_FLAG_NO_PARTIAL_WILDCARDS` and
`X509_CHECK_FLAG_NEVER_CHECK_SUBJECT`: matching SANs are required, no common-name
fallback is allowed, and only a complete leftmost wildcard label is eligible.
IP matching requires the IP SAN type, never a numeric DNS SAN. DNS names use
OpenSSL's ASCII/A-label input contract; the patch adds no IDNA normalization.
This deliberately rejects existing deployments that relied on CN-only leaves.

The locked quictls/OpenSSL archive includes the exact contracts in
`doc/man3/X509_check_host.pod` and
`doc/man3/SSL_CTX_set_tlsext_servername_callback.pod`; see also the
[OpenSSL 3.0 matching documentation](https://docs.openssl.org/3.0/man3/X509_check_host/)
and [SNI documentation](https://docs.openssl.org/3.0/man3/SSL_CTX_set_tlsext_servername_callback/).
No permissive trust manager, validation-disable flag, resolved-IP substitution,
plaintext fallback or process-wide signal-ignore wrapper is added.

## Separately pinned curl signal fix

The source investigation found a pre-existing signal-handling defect in curl
8.9.1. Both the original routing-only library and the hostname-only build let
Commo.shutdown reach curl_multi_cleanup/connc_close_all and replace the JVM's
caught SIGPIPE disposition with SIG_DFL. Read-only `/proc/self/status`
observations and raw-argument strace identified that transition; the observed
crash was a later JSSE close-notify write through libnio.

The separate dependency patch backports the exact one-line upstream correction
[3eec5afbd0b6377eca893c392569b2faf094d970](https://github.com/curl/curl/commit/3eec5afbd0b6377eca893c392569b2faf094d970):
initialize `sigpipe_ignore.no_signal` to TRUE. This makes the first apply save
and temporarily ignore the existing handler, so restore reinstates the real
JVM handler instead of a zero-initialized default. No Java or application signal
handler is installed. This remains **curl 8.9.1 plus an explicit upstream patch**,
not a current curl release or acceptance of its other security properties.

The lock binds the patch to the exact curl archive/version and before/after
`lib/sigpipe.h` hashes. The native recipe applies it after the official TAK
unpack/patch step and before curl configuration/compilation. Resumption accepts
only the exact original or already-patched file; altered or symlinked files fail.
The dependency patch participates in the build-cache fingerprint. The standalone
runner verifies patched source bytes and records the actual static curl archive,
JNI, runtime closure and patch hashes. As with other local smoke receipts, this
is a trusted-local incremental build proof, not a hermetic build attestation.

`CommonCommoSignalSmoke` reads the Linux SIGPIPE caught/ignored/blocked masks
before native initialization and after three construction/shutdown cycles. It
requires the ordinary JVM caught, unblocked disposition to remain unchanged,
then checks a real reset-peer Java write fails with SocketException instead of
terminating the JVM. The TLS smoke also checks abrupt peer closure is reported
by the native interface after authenticated bidirectional traffic. All chain,
client-certificate, identity, SNI and routing checks still run. Earlier failing
prefixes and receipts remain separate; they are not rewritten as successful.

## Compatibility boundary

This proves the listed loopback SSL streaming identity cases only. IPv6,
certificate revocation, QUIC/HTTPS/enrollment identity policy, TAK Server
interoperability, dependency security, hermetic packaging, map/GL behavior and
a complete TAKX build remain outside this acceptance. The library still reports
public CommonCommo 1.17.2 with project patches, never 1.22.3. Both official client
candidates remain unaccepted.

Fast guard tests do not load JNI or open sockets:

```bash
python3 -B -m unittest discover -s takx -p test_tls_guards.py -v
```
