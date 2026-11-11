# Experimental TAKX foundation

This opt-in component builds **public CommonCommo 1.17.2 with a local streaming-contact routing patch**, including its Java JAR and Linux amd64 JNI implementation. It does not build TAKX, create a desktop container, provide a replacement SDK, or complete [issue 376](https://github.com/jonathanagustin/uds-takserver/issues/376).

The existing `upstream/atak-civ` gitlink supplies the official source. [sources.lock.json](sources.lock.json) pins its revision, the actual CommonCommo version and nine source archives by SHA256, size and official public URL. TAKX source revisions in that file are research references, separate from the native build inputs. The optional `upstream/takx` gitlink pins the official 5.8 source; this build does not initialize or compile it. No TAK.gov account or private artifact is used by this foundation.

Evaluate both pinned official TAKX 5.7 and 5.8 profiles, preferring 5.8 after full compilation and runtime/interoperability checks pass. Neither client has passed those checks. Both still require complete desktop Kernel support and full client integration tests for the local streaming-contact adaptation; missing-type counts alone do not establish compatibility.

The optional [desktop compatibility prototype](compat/README.md) supplies real bitmap/Canvas, font, Context/resource, utility, Unix metadata and SQLite behavior. Its checked-in runners compile the complete public Kernel port module and exercise focused consumers. The separate opt-in [public Kernel compiler recipe](kernel-java/README.md) reproduces the engine, port and annotation desktop Java profile with frozen input hashes and zero compiler errors. The explicit `--scope engine-shared` option also compiles all 231 shared sources; neither scope assembles a complete Kernel SDK or compiles either TAKX client. See the [client feasibility checkpoint](CLIENT-CHECKPOINT.md). Its default dependency profile addresses the [recorded direct-dependency advisories](kernel-java/DEPENDENCIES.md), with the historical baseline kept as an explicit option; it is compilation evidence, and complete client/runtime acceptance remains outstanding. This independently implemented slice is not the upstream AndroidPort artifact and is not installed by the server package.

Follow [SDK integration](SDK-INTEGRATION.md) for the native Kernel integration,
full JNI runtime and client acceptance milestones.

The opt-in [public native dependency profile](native-deps/README.md) source-builds
Draco 1.5.7 and verifies selected TinyGLTF/Khronos header inputs. Real codec and
PIC probes cover that dependency only; it does not supply a Kernel SDK, JNI,
map rendering or either TAKX client.
The separate [LAS native profile](native-las/README.md) builds public libLAS,
LASzip and Boost sources with real LAS/LAZ, seek/reset, error and PIC probes.
The [Assimp native profile](native-assimp/README.md) builds the official core and
matching Java/JNI bindings, with ordinary model-data and zero-warning JNI checks.
The [historical PROJ profile](native-proj/README.md) builds unchanged PROJ 4.9.1
with real coordinate and PIC checks; modern API and security acceptance remain open.
The [SQLCipher native profile](native-sqlcipher/README.md) builds its Tcl and
OpenSSL prerequisites from source and checks encrypted databases and PIC linking.
The [historical GEOS profile](native-geos/README.md) is a bounded static/PIC
source experiment with real C geometry and malformed-input controls. Its
component result does not establish Spatialite, target ABI or TAKX acceptance.

The separate opt-in [GIS Java source recipe](gis-java/README.md) generates the official modified GDAL wrappers and compiles jassimp with a real consumer API probe. It has its own source lock and cache; it neither builds native GIS/JNI libraries nor completes the engine or either client.

The opt-in [UI Java source recipe](ui-java/README.md) rebuilds public desktop
dependency candidates for compiler probes. Its default original-source profile
and separate experimental Wizard reference preserve actual source identities;
they do not establish a working TAKX client.

## Run locally

Use Linux amd64, JDK 17 (`JAVA_HOME`), Python 3, Git, GNU make, GCC/G++, Perl, Ant, dos2unix, patch, tar, pkg-config, coreutils and the usual C/C++ build headers. The source archive configure scripts are already generated. These are optional local prerequisites; no default task or GitHub workflow installs or runs this component.

```bash
GIT_LFS_SKIP_SMUDGE=1 git submodule update --init upstream/atak-civ
export JAVA_HOME=/path/to/jdk-17
./takx/build-commoncommo.sh
```

The script retrieves only the nine locked source archives through official public raw/media URLs, validating bytes before materializing them. It rejects a wrong source revision, changed tracked build/code inputs, an unexpected CommonCommo version, or corrupt archives/cache entries. `TAKX_OFFLINE=true` forbids downloads; already verified source archives must be present or cached.

Caller-controlled paths and resource limits:

| Variable | Default / meaning |
|---|---|
| `ATAK_SOURCE_DIR` | Existing initialized `upstream/atak-civ`; an alternate official checkout must match the lock |
| `TAKX_BUILD_DIR` | `$XDG_CACHE_HOME/uds-takserver/takx/build/<source-path-hash>/commoncommo`, isolated install/build prefix |
| `TAKX_CACHE_DIR` | `$XDG_CACHE_HOME/uds-takserver/takx/sources`, SHA256-addressed public source archives |
| `TAKX_JOBS` | `2`; only `1` or `2` accepted; dependency installs stay serial |
| `TAKX_OFFLINE` | `false`; `true` disables archive downloads |

Use `--verify-only` to check/materialize source inputs without compiling. Use `--smoke-only` to exercise an already built JAR/JNI pair without compiling native code or marking it as a completed build cache. Before compiling, a normal build records its input key in `build-inputs.json`. Only an interrupted prefix with that same key may resume. Success records all prefix runtime `.so`, `.a` and JAR hashes in `build-state.json`; unchanged invocations verify those outputs, skip native compilation, and still run the real smoke. A changed input/toolchain key, corrupt completed output or unknown nonempty prefix is refused: choose a fresh `TAKX_BUILD_DIR`. The script does not delete or adopt existing outputs.

When `XDG_CACHE_HOME` is unset, its base defaults to `$HOME/.cache`. The build subdirectory uses the first 12 SHA256 characters of the canonical ATAK source-checkout path to separate checkouts/worktrees; the full build-input key still guards reuse. Defaults stay outside the repository because upstream archives extract private-key test fixtures. An explicit in-repository `TAKX_BUILD_DIR` can cause repository secret scans to flag those fixtures; prefer an external directory rather than allowing them through scans.

Source/output paths must not contain whitespace because the upstream Makefiles do not quote every path. A build may take several minutes and uses an isolated prefix; it does not replace system OpenSSL or other libraries. The native key covers the consumed ATAK/archive/version lock fields, build recipe and toolchain identity, not unused TAKX reference metadata or the separately rerun smoke assertions. Patch hashes and the source-staging helper also participate in the native input key. The local cache is an optimization, not an official artifact signature or a reproducible-build attestation. For a fresh build, choose a new empty `TAKX_BUILD_DIR`; do not delete cache metadata to relabel existing objects.

## What is built and tested

The pinned native inputs are zlib, libiconv, libxml2, quictls/OpenSSL, nghttp2, curl, ngtcp2, protobuf and libmicrohttpd. Dependency installs are ordered because upstream's parallel multi-output OpenSSL install can race. The exact host protoc is built once; only the actual same-version PIC protobuf-lite library and headers are built for the target. CommonCommo's real static core is linked into its JNI shared library, and upstream Ant produces the auto-initializing Java JAR. The ordered, hash-locked CommonCommo patches are applied to an isolated copy exported from the pinned Git revision. They add a streaming-contact fallback and configured TLS endpoint verification without changing the upstream checkout or the reported upstream version.

The crypto smoke constructs a real native Commo instance, generates an ephemeral PKCS12, parses it with Java KeyStore and shuts down. It saves no certificate/private key.

The routing smoke uses real loopback TCP server sockets and a UDP receiver through the built Java/JNI/C++ stack. It checks the selected stream and recipient callsign, replacement, discovered-stream priority, removal without deleting a discovered contact, fallback after the discovered interface is removed, direct UDP priority, and rejection of unknown or removed stream IDs. It runs after normal and cached builds. These are local transport tests, not TAK Server interoperability, TLS handshake, enrollment, map rendering or full TAKX compatibility proof.

The successful native investigation used the isolated quictls `libssl.so.81.3` / `libcrypto.so.81.3`. Curl also detected host libraries for IDN2, RTMP, PSL, Zstandard and Brotli; the JNI runtime additionally needs the usual C/C++ runtime and loader. This recipe is **not yet a hermetic runtime package**: a future container must capture/audit that closure or deliberately configure dependency features and retest. The cache fingerprint does not pin every host library.

The separate [mutual TLS loopback smoke](TLS.md) exercises real source-built
transport with ephemeral certificates, configured DNS/IP SAN matching, DNS SNI,
CoT delivery and wrong-name/wrong-CA/client-certificate rejection. It also
checks SIGPIPE disposition preservation through shutdown using a separately
pinned upstream curl 8.9.1 correction. See [dependency patch provenance](dependency-patches/README.md).
Loopback identity acceptance does not establish TAK Server interoperability,
dependency security or full client compatibility.

## Compatibility boundary

Current TAKX requires CommonCommo 1.22.3. Public 1.17.2 supports the inspected enrollment, streaming transport and mission-package call shapes, and the local patch implements `configKnownEndpointForContact(uid, callsign, streamId)`. A configured route is a separate fallback: active discovered routes retain precedence, and the fallback uses the existing streaming manager rather than converting a stream ID to UDP. Both optional arguments must be null to remove the fallback; an unknown stream ID fails. Existing fixed-UDP routes retain their original behavior. Removing a streaming interface leaves its explicit contact configuration in place until cleared or replaced. Sends through that removed ID fail; they do not move to another live stream or invent a UDP route. Clear that configuration with both optional arguments null. Clearing an already absent contact is rejected, matching the existing fixed-endpoint API rather than silently recreating it. Full client integration remains required before claiming compatibility. Full TAKX also needs the Kernel, patched WorldWind and other dependencies.

Keep upstream changes as reviewable diffs under [patches](patches/README.md). Do not relabel this library as 1.22.3, fabricate SDK classes or silently suppress unsupported functionality.

## Check the foundation

```bash
python3 -B -m unittest discover -s takx -p 'test_source_inputs.py' -v
bash -n takx/build-commoncommo.sh
```

Source/hash guard tests are local and do not fetch archives or compile native dependencies. They complement the actual JAR/JNI smoke, which requires the real source-built outputs.
