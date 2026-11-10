# Opt-in official modified GIS Java bindings

This separate recipe builds the Java portions of the official modified GDAL
2.4.4 and Assimp 4.0.1 source archives. It generates 58 GDAL Java wrappers and
compiles 42 jassimp classes, then compiles a real consumer of the required GIS
APIs. It does not build native libraries, load JNI, complete the Kernel engine,
or establish either TAKX candidate's compatibility.

These archives are **not** part of the mandatory CommonCommo source lock or
build path. No default task or workflow calls this recipe. No SDK artifact is
renamed to satisfy `gov.tak.thirdparty` coordinates.

## Prerequisites and invocation

The local acceptance host was Linux amd64. Provide Python 3.9+, a trusted JDK 17 (`java`, `javac`, `jar` on PATH), and trusted
SWIG **4.3.0**. No tools are installed or downloaded by the recipe. A reviewed
example is Debian `swig 4.3.0-1` from signed official repository metadata; package
hash and source are recorded in the separate [lock](sources.lock.json).
For a staged package, set `GIS_JAVA_SWIG` to its executable and `SWIG_LIB` to its
matching `usr/share/swig/4.3.0`. Do not use an unreviewed binary just because it
reports the expected version.

```bash
export PATH=/path/to/trusted/jdk-17/bin:$PATH
export GIS_JAVA_SWIG=/path/to/trusted/swig
# Only needed for a separately staged SWIG installation:
export SWIG_LIB=/path/to/matching/swig/4.3.0
python3 takx/gis-java/build.py
```

| Variable | Default / behavior |
| --- | --- |
| `GIS_JAVA_CACHE_DIR` | `$XDG_CACHE_HOME/uds-takserver/gis-java/archives`, SHA256-addressed verified source archives |
| `GIS_JAVA_BUILD_DIR` | `$XDG_CACHE_HOME/uds-takserver/gis-java/build`, isolated source/generated/classes/JAR prefix |
| `GIS_JAVA_SWIG` | `swig` on PATH; exact reviewed version required |
| `SWIG_LIB` | Tool-reported library directory unless supplied; its file hashes enter the input key |
| `GIS_JAVA_OFFLINE=true` | Forbids missing-source downloads; already verified archives must be cached for a fresh build |

When `XDG_CACHE_HOME` is unset, its base is `$HOME/.cache`. Both cache and build
prefix must be outside this checkout and separate from each other. The normal
first build retrieves about 60 MB of official source archives; existing files
are verified by size and SHA256, never silently replaced after corruption.
To preseed offline sources, name each archive `<locked-sha256>.tar.gz` in the
external source cache. HTTPS URL, revision, size and hash are all in the lock.

Build steps run serially. Java compiler heaps are capped at 256 MiB and active
processor count at two. Only reviewed source/header/interface paths are copied
from the archives; no bundled executables or model assets are extracted.
Absolute/traversal paths, selected links/duplicates and oversized source payloads
are refused. SWIG produces native wrapper **source** as part of Java generation;
that C/C++ is never compiled here. Original source and license notices remain
in the external prefix, and notices are included in the JARs.

## Outputs and cache behavior

Successful outputs are `gdal-2.4.4-mod-java.jar` and
`assimp-4.0.1-mod-jassimp-java.jar`, with generated sources, compiler logs,
`build-inputs.json` and `build-state.json`. The input key includes the separate
lock, recipe, compile probe, tool versions/binary hashes and SWIG resources.
The state hashes every managed output, not only JAR names.

An unchanged completed cache verifies those hashes and recompiles the API probe
in a new temporary directory without regenerating or recompiling the bindings.
An unknown, incomplete, changed or corrupted prefix is refused. Choose a **new
empty** `GIS_JAVA_BUILD_DIR` after changing inputs; do not delete state to relabel
old outputs. The recipe does not delete or adopt unknown build prefixes.
Source cache corruption is also refused when those archives are consumed.
A completed cache can be reused without redownloading its source archives.
This local integrity guard is not a signed artifact or reproducible-build
attestation, and it does not pin every host library used by the trusted tools.

The [compile-only API probe](CompileApiProbe.java) uses real `Dataset.Interrupt`,
`Interrupted`, `ClearInterrupt`, `CE_Interrupted`, integer color-table entries,
and jassimp IO/allocator/import signatures. It is never executed: native methods
and class initialization need a matching source-built GIS/JNI runtime, which is
not present merely because Java compilation passes.

## Evidence and remaining scope

[PROVENANCE.md](PROVENANCE.md) records the official source hits, license and tool
review, public alternative distinction, and actual full-engine compiler result.
The source-built Java artifacts removed the specific GDAL fork and jassimp Java
API errors. That initial GIS-only experiment emitted 1,303 engine diagnostics,
chiefly missing Android desktop APIs and cascades. The later integrated
[desktop compatibility investigation](../compat/FINAL-APIS.md) reached zero Java
compiler errors. Its full-engine compile recipe remains local research, while
this GIS Java recipe is checked in. Both TAKX 5.7 and 5.8 remain candidates;
compiler results neither select the older one nor establish a working client.
Native interruption behavior, JNI lifetimes, driver/data coverage, map rendering,
and client interoperability remain untested here. The full native recipe includes
libkml, PROJ, OGDI, SQLite, PDFium and optional proprietary integrations; this
recipe does not silently disable those features and call the result equivalent.

Run the fast offline guards without downloading or compiling GIS sources:

```bash
python3 -B -m unittest discover -s takx/gis-java -p test_build.py -v
```
