# Public Kernel SDK integration

TAKX needs a working Kernel SDK: Java classes, native libraries, JNI bindings and
resources that work together. The current work connects the public components to
actual Kernel APIs before assembling that runtime.

The source baseline is Kernel 8.30.5 at official ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`. Its identity stays separate from the
newer SDKs requested by TAKX. See the [client checkpoint](CLIENT-CHECKPOINT.md)
for both client versions and their remaining API differences.

## Integration stages

| Stage | What must work | Status |
| --- | --- | --- |
| Kernel database | Legacy Kernel database APIs with Spatialite, SQLCipher, GEOS, PROJ, XML and character conversion | Local functional, provider and strict-link checks passed |
| Kernel scene reader | Actual Kernel scene and mesh APIs with Assimp, GDAL and ZIP support | Local factory, mesh, provider and strict-link checks passed |
| Full native runtime | Complete Kernel and JNI targets with their real dependencies | Pending |
| Java SDK | Actual initialization followed by engine and GDAL JNI calls | Pending |
| TAKX client | Compilation, startup, rendering and server interoperability | Pending |

See the [database profile](kernel-spatial-db/README.md) and
[scene profile](kernel-scene/README.md) for reproducible commands and limits.

The first two stages produce local C++ integration artifacts. They do not yet
provide a loadable Java SDK or a desktop installer. Track the complete work in
[#477](https://github.com/jonathanagustin/uds-takserver/issues/477).
The legacy database check does not validate modern Database2 encrypted opening.

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
