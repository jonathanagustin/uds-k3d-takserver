# Pending exceptions and JNI input ownership

These findings use the actual generated GDAL wrapper from the first patched GIS
build, receipt SHA256
`07ab84a03c7de5e956c15f6bf7ca28c6b7f4a987ec23ec5e28498a54351d8cf3`.
Its `gdal_wrap.cpp` SHA256 is
`70d8209bff161d156a6c05a4cc4a00fd8266bf7bf81d8db23ad5715c2e08f2ec`.
That completed source-generation receipt remains historical evidence; it is not
reclassified as the new ownership profile or a native runtime qualification.

## Interruption error handling

The actual generated `Driver_CreateCopy__SWIG_0` wrapper calls the native helper,
then assigns its result, releases the filename UTF characters, destroys options
and returns. It has no Java exception translation or `ExceptionClear` after the
native call. The helper calls `GDALCreateCopy` and returns its result. Native CPL
error handlers print/suppress interruption errors without invoking Java in this
controlled path. A pending callback Throwable therefore is not intentionally
replaced by that wrapper's interruption handling.

The generic SWIG throw helper does call `ExceptionClear`. The actual `OGRErr`
output typemap calls that helper on native errors. Version 2 checks for an
existing pending Throwable before this translation. The real progress control
is prepared for both `UseExceptions` and `DontUseExceptions`, requiring identity
with the original Java Throwable. Both real runtime modes passed with the same original Throwable.

## Scoped ownership correction

In the generated CreateCopy wrapper, `GetStringUTFChars(jarg2)` occurs before
options conversion. Early returns on throwing/null Enumerations bypass its tail
release. Freeing the CSL list alone does not release that earlier acquisition.

Version 2 patches official `swig/include/java/typemaps_java.i`, rather than editing
generated wrappers. For C++ wrappers it introduces scoped owners for ordinary
`char*`/`const char*` UTF inputs and options CSL lists. Their function-scope
destructors run on successful and early returns. UTF release is allowed with an
original Throwable pending; neither owner clears it. Tail cleanup becomes empty
for owned UTF inputs and a C++ no-op for owned options, avoiding double release.
C wrappers retain their existing CSL cleanup; the pinned gdalconst module has no
options/UTF-input wrappers.

Actual v2 generation produced 331 scoped UTF owners and 90 CSL owners. The
108 custom raw UTF acquisition/release pairs remained unchanged. Genuine native
compilation and Enumeration/progress/null controls passed with zero checked-JNI
diagnostics. These results are scoped to the exercised paths; see the separate
[artifact qualification](KML_PROFILE.md#qualification).

## Remaining resource patterns

The same v1 generated-source pattern appears before options conversion in:

- GDAL: 19 wrappers, including filename inputs and three primitive-array cases.
- OGR: four wrappers with prior UTF inputs.
- GNM: two wrappers with prior UTF inputs.
- OSR: one wrapper with a prior UTF input.

Ordinary UTF and CSL ownership is the scope of version 2. Custom multiargument
string maps, primitive arrays and buffers still have independent tail-cleanup
paths. Concrete array cases include Dataset.AdviseRead and RasterizeLayer
(overloads 0 and 1). They need separate ownership/critical-region review; this
change does not claim to resolve them or qualify all GDAL APIs.

The shared `takx/jni_diagnostics.py` classifier rejects mixed-case checked-JNI,
critical-array/string warnings and JVM/native errors. It is only a rejection
gate: a quiet log never establishes functional or provenance acceptance. Native
producer gates still require actual success markers and exact ELF identities.
