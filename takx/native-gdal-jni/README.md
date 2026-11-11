# Genuine reduced GDAL Java JNI precursor

This opt-in harness consumes the completed local KernelScene GIS producer and
GIS Java source-generation receipts. It verifies the original pinned sources,
configuration, tools, installed products, all GDAL objects, and archive object
closure with `kernel-scene/kernel.py`; it verifies the GIS Java recipe and every
recorded output with `kernel-java/build.py`. It never rebuilds GDAL or changes
its source algorithms, reduced driver profile, accepted receipts, or tools.

Run `python3 takx/native-gdal-jni/build.py --help` for required explicit paths.
The output must be new, external, and separate from all inputs. Commands run
sequentially with a ten minute deadline, bounded private logs, and a one GiB
output check. A failure leaves the proof directory and `failed.json` intact.

The shared-provider contract is `lib/libgdal.so` built from the whole verified
PIC static GDAL archive, with the verified PROJ and zlib archives and the recorded
platform link dependencies. The five actual generated SWIG wrappers link into
`lib/libgdalalljni.so` against that shared provider with strict unresolved-symbol
checks and `$ORIGIN` runtime lookup. Future Kernel integrations must link to
this same shared `libgdal.so`; embedding another static GDAL engine would violate
the contract. No SDK replacement, version alias, symbol stub, or feature-removal
workaround is supplied.

The Java probe calls GDAL version/registration, exact MEM raster write/read,
WGS84 transformation, modified Dataset interrupt methods, and missing-file error
handling. The receipt hashes the actual mapped GDAL providers. Success remains
a GDAL JNI precursor: full Kernel native/JNI, renderer, SDK, and client acceptance
remain pending.

Run `python3 takx/native-gdal-jni/test_build.py` for the offline dependency guards.
Compiler dependency files enumerate the actual non-system wrapper inputs; inputs
outside the verified source, installed header, JDK, and frozen wrapper trees fail.
`consumed-header-hashes.json` records those bytes, and
`wrapper-header-hashes.json` inventories the offered original supporting headers.
JDK executables must match the GIS Java receipt. Compiler/linker tool hashes and
the initial harness/probe hashes are recorded and checked for changes.
`jni-dynamic.log` records the shared-provider dependency, and
`jni-defined-symbols.log` checks that JNI does not define `GDALVersionInfo`.

The complete receipt binds the executed verifier/helper/lock closure, frozen
wrapper inputs, compiler dependency inputs, object and shared-library outputs,
probe classes, JAR, tools, and all mapped ELF providers. Both shared libraries
must have no TEXTREL and only the reviewed GDAL/platform NEEDED entries. Runtime
providers must come from the prehashed selected JDK, reviewed platform runtime
files, and the two freshly linked GDAL libraries; all `LD_*` and Java injection
variables are removed from child environments.

Use `python3 takx/native-gdal-jni/build.py --replay /absolute/proof` to verify an
existing proof without compilation, or set `GDAL_JNI_PROOF=/absolute/proof` while
running the guard tests to also rerun the real Java JNI controls in a fresh
private directory and verify the observed libraries. Default guard tests never
compile native code or load JNI.
The trusted external JDK/platform runtime bytes are recorded as host inputs;
they are not represented as source-built SDK outputs.
