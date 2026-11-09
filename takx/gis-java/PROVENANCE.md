# Authoritative source and Java-only acceptance

The exact official source is
[TAK-Product-Center/atak-civ at 9f6893dd657feacc35ec5de03dad721c2e44170e](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).
Its [BUILDING.md](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/BUILDING.md)
names the modified source archives; the Git LFS pointers provide the exact sizes
and SHA256s pinned separately in `sources.lock.json`. GitHub code search cannot
inspect source inside those LFS tarballs. No unofficial mirror implementation or
prebuilt GIS SDK was adopted.

Source review found the required behavior in these GDAL archive members:

| Member | Concrete source evidence |
| --- | --- |
| `gdal/port/cpl_error.h:54` | `CE_Interrupted = -999` |
| `gdal/gcore/gdal_priv.h:539–541` | Native virtual `Interrupt` and `ClearInterrupt` |
| `gdal/gcore/gdaldataset.cpp:2344` onward | Mutex-protected interrupt state, consuming `Interrupted`, and clearing logic |
| `gdal/swig/include/Dataset.i:456–465` | SWIG methods call the actual GDAL interrupt C entry points |
| `gdal/swig/include/gdalconst.i:135` | Exports `CE_Interrupted` |
| `gdal/swig/include/java/typemaps_java.i:104–160` | Packed ARGB `jint`/Java `int` color entries in Android and desktop branches |

The native implementation is substantive, not an empty callback or a constant
invented to make Java compile. The official leaf depversion is
`2.4.4-tak-1.0.1`, while the engine requests bundle coordinates under
`takthirdparty 4.2.4`; they are different version layers. The Assimp archive
contains 42 core jassimp Java sources, modified JNI source, README, Ant recipe and
actual IO/allocator interfaces. Its separate depversion marker is `ttp-3.0.2`.
The recipe labels its outputs by their source archives rather than impersonating
an official artifact version.

GDAL `LICENSE.TXT` includes MIT-style GDAL/OGR permission and separate bundled
component notices; this is not a claim that every driver has one license.
Assimp's license and jassimp source headers contain BSD-style three-clause terms.
Its non-BSD test-model exception is retained in the notice, but no model assets
are selected for these Java artifacts. Original notices are preserved.

The reviewed SWIG tool was the official Debian `swig 4.3.0-1` amd64 package,
SHA256 `fe8749993e720a232582c13a5ddcaeb074c435a1f1c6ed2ffe0db597a972a069`,
retrieved using configured signed Debian snapshot metadata and extracted in
scratch with `dpkg-deb -x`. No package install or maintainer script was run.
Its libc, libgcc, libpcre2 and libstdc++ requirements were already available.
SWIG 4.3.0 differs from the archive documentation's legacy 3.0.8 example, so the
actual generator/resources are part of the build input fingerprint.

Local acceptance used real SWIG interfaces to generate all 58 GDAL Java wrappers,
then Temurin 17 with `--release 11 -proc:none` to compile those and all 42 jassimp
classes. The actual consumer probe compiles, without executing JNI. A complete
public desktop engine attempt with those source-built JARs, the real compat slice
and declared public Java dependencies still failed with 1,303 diagnostics.
The specific GIS Java package/fork gaps disappeared; broader Android graphics,
SQLite, Uri, Parcel and utility behavior remains missing. Diagnostics include
cascades and are not counts of independent APIs.

For comparison, the small official Maven Central `org.gdal:gdal:3.13.0` Java JAR
was available, but lacked the custom interrupt APIs and returned `java.awt.Color`
rather than integer color entries. It is not a replacement for this fork and is
not used by this recipe. Neither Java compile success nor inspecting the real
native implementation establishes matching JNI symbols, concurrent cancellation,
color conversion at runtime, driver coverage or a full TAKX client. Those require
separate source-built native and interoperability acceptance.
