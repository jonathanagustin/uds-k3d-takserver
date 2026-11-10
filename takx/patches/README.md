# Upstream patches

The optional Kernel port test applies `0001-kernel-remove-unused-colorfilter-import.patch` to a temporary copy of official ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e`. It removes only an unused import, allowing the real marshal registry to compile without supplying a placeholder Android ColorFilter. The test pins the patch hash and exercises all 18 blend-mode round trips; no drawing behavior is removed. This patch is not an input to the native CommonCommo build.

`0100-commoncommo-stream-contact-fallback.patch` applies only to official ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e`, CommonCommo 1.17.2. The explicit `patches` list in `sources.lock.json` records order, upstream identity and SHA256. Unlisted patches are not applied by the native build.

The patch adds the Java/JNI/C++ streaming-contact fallback needed by both pinned TAKX profiles. It validates an existing stream ID, keeps configured and discovered endpoints separate, retains direct/discovered routing priority, and preserves discovery when the configured fallback is removed. It uses the normal streaming send path and recipient callsign, not the older fixed-UDP API. The library remains identified as patched public 1.17.2, never 1.22.3.

`CommonCommoRoutingSmoke.java` exercises actual loopback TCP and UDP delivery through native code. Run it with the built JNI/JAR as part of `build-commoncommo.sh`. Source guard tests check patch hashes, revision restrictions, failed application and staging isolation. Discovery readiness uses an ordered sentinel contact callback, not a fixed sleep. Tests also keep another stream live when the configured interface is removed and verify failed sends do not leak there. An already absent contact rejects repeated clearing. Retire this patch only after a matching official source API passes the same transport tests.

`0101-commoncommo-stream-server-identity.patch` follows the routing patch on the
same public 1.17.2 source. It retains the caller's original endpoint as immutable
identity, sends DNS SNI, and requires the matching DNS/IP SAN after the existing
CA-chain check and before Up/authentication/CoT. OpenSSL rejects mismatches,
CN-only fallback and partial-label DNS wildcards. No client-certificate or CA
checks are removed. [Real loopback tests and remaining dependency limits](../TLS.md)
cover DNS/IP positives, DNS SNI, trusted-CA wrong-name leaves, wrong SAN types,
CN-only leaves, wrong CA/client trust and missing client certificates.

Future changes belong here as small, ordered diffs against a recorded upstream revision. Each patch must state the concrete incompatibility, intended behavior, applicable version and tests. Apply patches deterministically and include their hashes in build inputs before enabling them. Keep substantial upstream code in its upstream checkout rather than copying it into an untracked compatibility SDK.

A repository-local adapter is appropriate only when it implements real, tested behavior at an integration boundary. Do not add placeholder SDK classes, rename an old artifact to satisfy a newer dependency, treat a fixed-UDP endpoint as a TLS streaming route, or silently remove features. Unsupported capabilities must be visible and covered by tests; upstream fixes should remain easy to review and retire when a matching source release becomes available.

`0200-takx-nasa-text-renderer.patch` changes one import in the pinned TAKX 5.7/5.8
`AOverlayLayer` production consumer. Stock NASA WorldWind 2.2.1 returns its own
`gov.nasa.worldwind.render.TextRenderer` from `OGLTextRenderer`; the consumer had
expected JOGL's different class. The patch keeps the real factory, cache and
rendering calls. It is an explicit project compatibility patch, not the unavailable
upstream `2.2.1-TAKX-4` patch set. [Source pins and staging guards](../worldwind-consumers/README.md)
apply it only to verified source copies. Neither the native build nor Kernel recipe
applies this patch automatically.
