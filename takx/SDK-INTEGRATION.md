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
| Native build | All 815 Core, JNI and Cesium translation units built and linked against verified dependencies | SDK resource packaging and other target ABIs |
| Kernel APIs | Native geometry/projection, encrypted Database2 and GDAL raster controls passed with zero JNI warnings | Model, format and renderer coverage |
| Graphics | Source-built GLES dispatch rendered an ES 3 pixel on host Mesa | Kernel renderer and hardware paths |
| SQLite JDBC | Its embedded backend is isolated; both crypto load orders passed | Joined SDK/JDBC runtime |
| CommonCommo | Lifecycle, routing, TLS identity and throwing-logger controls passed with zero JNI warnings | QUIC peer and TAK Server interoperability |
| Joined runtime | Kernel database/GDAL and Commo controls passed in one JVM, in both native load and Java initialization orders | SDK packaging and application-level coverage |
| Component package | Stock Kernel resource loader passed four fresh JVM controls, relocation and a missing-resource check | Renderer, CommonCommo integration and other host ABIs |
| TAKX client | Pending | Compilation, startup, rendering and server interoperability |

Start with the [complete native profile](kernel-native/README.md). Its fresh
build and strict runtime controls are opt-in; ordinary CI runs offline guards.
The component checks also have [database](kernel-spatial-db/README.md),
[scene](kernel-scene/README.md) and [MDBTools](native-mdbtools/README.md) profiles.
The [Java compiler](kernel-java/README.md), [GLES](native-gles/README.md),
[GDAL JNI](native-gdal-jni/README.md) and [crypto](native-crypto/README.md)
profiles document runtime prerequisites and their limits. The
[Cesium](native-cesium/README.md), [LibKML](native-kml/README.md),
[Curl](native-curl/README.md) and [SQLite JDBC](sqlite-jdbc/README.md) profiles
cover the dependency builds and backend isolation.

The [local Draco cache](registry-cache/README.md) packages a verified component
and tests relocation at two prefixes. Registry publishing and publisher
authentication remain separate work in [#482](https://github.com/jonathanagustin/uds-takserver/issues/482).

The [component package](sdk-package/README.md) assembles the verified Kernel
classes, native resources, headers and notices. Its stock-loader controls use a
private extraction directory and verify the actual mapped libraries. This is
not yet a complete SDK or desktop installer. The native
profile validates modern Database2 encryption; the graphics result still uses
host Mesa. Joined checks cover Kernel 8.30.5 and CommonCommo 1.17.2 loopback
controls, including clean JVM shutdown. They do not establish QUIC peer, renderer
or TAK Server interoperability. See the [CommonCommo profile](native-commoncommo/README.md)
for its separate source build and verified JNI continuation.
Track the complete work in [#477](https://github.com/jonathanagustin/uds-takserver/issues/477).

The [client interop source profile](kernel-client-interop/README.md) adds real
role-icon, font and viewport behavior, plus Java/JNI bridges to existing native
label and scene APIs. Its headless controls pass; the new JNI paths still need
runtime qualification. The [WorldWind interop profile](worldwind-java/README.md)
adds rendering and picking hooks with real-class dispatch and coordinate tests.
Headed rendering, thread handoff and client launch remain separate checks.

## SDK acceptance

Package the verified Java classes, native runtimes, resources and required
notices into a distribution that loads its own providers.
The public-source feature profile must state its supported formats. Optional
proprietary codec resources can be omitted when the compiled libraries do not
depend on them; the upstream loader skips absent resources.

A normal return from `EngineLibrary.initialize()` is insufficient: it catches
errors internally. Acceptance must call actual engine and GDAL JNI methods,
verify their results, and exercise database, geometry, model and rendering paths.
CommonCommo still needs an actual TAK Server interoperability check.

Only then can the client builds use these artifacts. Prefer TAKX 5.8 after its
actual API, runtime and interoperability checks pass. Source identities and
reported versions must remain accurate throughout integration.
