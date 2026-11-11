# Public Kernel SDK integration

TAKX needs a working Kernel SDK: Java classes, native libraries, JNI bindings and
resources that work together. The current work connects the public components to
actual Kernel APIs before assembling that runtime.

The source baseline is Kernel 8.30.5 at official ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`. Its identity stays separate from the
newer SDKs requested by TAKX. See the [client checkpoint](CLIENT-CHECKPOINT.md)
for both client versions and their remaining API differences.

## Integration stages

| Stage | Local result | Remaining acceptance |
| --- | --- | --- |
| Native components | Kernel database/scene and MDBTools controls passed | Complete native dependency graph and Kernel provider integration |
| Dependency graph | All 18 Cesium targets compiled; LibKML and Curl passed native controls | Complete Kernel/JNI integration and runtime coverage |
| SQLite JDBC | Genuine JNI exports isolated from the embedded SQLite backend; both crypto load orders passed | Combined SDK runtime |
| Graphics prerequisite | Source-built GLES dispatch rendered an ES 3 pixel on host Mesa | Kernel renderer, target platform and hardware paths |
| GDAL Java JNI | Five real wrappers share one GDAL engine; Java raster, coordinates, interrupt and error checks passed | Full Kernel integration and supported-format coverage |
| JNI build headers | 118 generated headers cover all 109 names required by pinned native sources | Compile and load the complete Kernel JNI target |
| CommonCommo | Source-built Core plus corrected JNI passed lifecycle, routing, TLS identity and throwing-logger controls with zero JNI warnings | Joined Kernel runtime, QUIC peer and TAK Server interoperability |
| Combined runtime | Two isolated crypto groups passed both load orders and encryption checks | Actual Kernel/CommonCommo loading, routing and QUIC transport |
| TAKX client | Pending | Compilation, startup, rendering and server interoperability |

Reproduce the native checks with the [database](kernel-spatial-db/README.md),
[scene](kernel-scene/README.md) and [MDBTools](native-mdbtools/README.md) profiles.
The [Java compiler](kernel-java/README.md), [GLES](native-gles/README.md),
[GDAL JNI](native-gdal-jni/README.md) and [crypto](native-crypto/README.md)
profiles document runtime prerequisites and their limits. The
[Cesium](native-cesium/README.md), [LibKML](native-kml/README.md),
[Curl](native-curl/README.md) and [SQLite JDBC](sqlite-jdbc/README.md) profiles
cover the remaining dependency builds and backend isolation. Native builds are
opt-in; ordinary CI runs offline guards.

These results do not yet provide a complete Java SDK or desktop installer.
The legacy Kernel database check does not validate modern Database2 encrypted
opening. The graphics result uses the existing host Mesa stack; the crypto
experiment does not complete a QUIC handshake or join Kernel with CommonCommo.
The [CommonCommo profile](native-commoncommo/README.md) records its separate
functional controls and the verified JNI-only continuation.
Track the complete work in [#477](https://github.com/jonathanagustin/uds-takserver/issues/477).

## SDK acceptance

Build the complete Kernel and JNI source sets against verified dependencies,
then package the Java classes, native runtimes, resources and required notices.
The public-source feature profile must state its supported formats. Optional
proprietary codec resources can be omitted when the compiled libraries do not
depend on them; the upstream loader skips absent resources.

A normal return from `EngineLibrary.initialize()` is insufficient: it catches
errors internally. Acceptance must call actual engine and GDAL JNI methods,
verify their results, and exercise database, geometry, model and rendering paths.
CommonCommo also needs a combined-runtime and server interoperability check.

Only then can the client builds use these artifacts. Prefer TAKX 5.8 after its
actual API, runtime and interoperability checks pass. Source identities and
reported versions must remain accurate throughout integration.
