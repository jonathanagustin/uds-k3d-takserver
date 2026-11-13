# GDAL KML profile preparation

The baseline reduced GDAL config explicitly disables Expat and LibKML. The actual
Kernel KML regression therefore fails to recognize its in-memory KML fixture.
This is separate from missing Java runtime resources and the GDAL JNI options
vector exception-check defect.

`kml_profile.prepare(kml_root, receipt_sha256, bindings, output, base_configure)`
prepares a private configuration from the existing genuine six-library LibKML
1.3/Expat 2.10 proof. It verifies complete installed inventories, Boost headers,
exact minizip/URI archive lineage and zlib artifact/producer identity. Inputs are
explicit paths and independently reviewed receipt/artifact hashes. It never
searches for or accepts host KML packages.

Bindings contain `minizip`, `uriparser` and `zlib` objects with `path`/`sha256`,
`zlibReceipt` with `path`, and `boostRoot`. The output must be fresh and disjoint.
The helper writes a private `libkml.pc` with the exact six static archives and
minizip/URI/Expat/zlib dependency group, and `configuration.json`. Both disabled
configure options are replaced in the passed baseline argument list; remaining
reduced-driver choices are preserved.

The existing `build.py` implements the opt-in profile. Supply all five additional
arguments: `--kml-proof`, `--kml-receipt-sha256`, `--kml-bindings`,
`--kml-bindings-sha256`, and `--gis-receipt-sha256`. Partial selection fails before
any build. The expected GIS receipt must come from the newly patched source
producer, not the previous frozen wrappers. CMake defaults to the executable on
`PATH`; use `--cmake /absolute/path/to/cmake` to select another installation. Its
resolved bytes are recorded. GCC reports its actual helper paths; the recipe
does not assume a distribution-specific backend directory.

The producer configures and compiles only genuine GDAL into a fresh tree; it
requires `HAVE_EXPAT=yes`, `HAVE_LIBKML=yes`, the verified static provider paths,
and the existing reduced-driver/static-PROJ contract. It binds original source
postimages, the complete resulting build tree, installed products, actual source
generation profile, all provider inputs, tools/backends, consumed JNI headers,
objects and both final shared libraries. It rechecks the accepted raw dependency
producer and all bound inputs. No Kernel translation units are rebuilt.

The link uses the exact private static group and hides Expat symbols. Dynamic
ELF checks reject host XML/KML/Expat libraries, and a symbol audit rejects escaped
`XML_*` definitions. A checked-JNI probe requires both genuine KML and LIBKML
drivers, reads authored KML coordinates, and executes original-Throwable
Enumeration/progress callback controls. Existing MEM/projection/error controls
and exact mapped-provider checks remain required. JNI warnings fail acceptance.

The optional profile has a parent-monitored 768 MiB inclusive output cap, 8 MiB
receipt reserve, 8 MiB complete log per command, 128 MiB per-file limit, one build
job, a one-hour total deadline and a 2 GiB physical free floor. Before output
creation it reserves the full 768 MiB above that floor. This requires at least
2,952,790,016 free bytes. Existing accepted artifacts remain inputs; no SDK is
edited in place. Failures are retained without automatic retry.

`gis-java/bounded_build.py` is the first stage: a fresh 48 MiB supervisor root,
2 MiB receipt reserve and 240-second bound around offline SWIG/Java generation.
It requires the independently hashed original GIS toolchain receipt and patch
utility, preserves exact qualified tools/resources, verifies the new complete
GIS producer output and records its new receipt SHA. Native stage execution is
a separate review step, binding that independently reviewed new SHA.

## Qualification

The v2 Java/SWIG source stage completed and produced unchanged public Java class
bytes. The first native attempt at source commit
`59587b12fbe16470febb343d1870525ce15eb8c3` compiled 1,073 actual GDAL objects and
linked both real libraries. Checked-JNI controls passed MEM raster/projection,
KML and LIBKML coordinates, null Enumeration rejection and preservation of the
original callback Throwable in both GDAL exception modes. No JNI or critical
region diagnostics were observed.

That producer still **failed** its last inventory check because GNU libtool
creates `.libs/libgdal.la -> ../libgdal.la`. The updated owned-tree inventory
admits exactly that relative internal metadata link and binds its regular
referent hash. Generic input and installed/shared-product scanners still reject
symlinks.

A separate evidence-only finalization verified the existing products, all 1,073
object/archive bodies, 1,343 JNI exports, source/tool/provider/header closures,
actual runtime log and mapped ELF identities. An independent audit rechecked
12,060 original files, both products, eight control classes and 19 mapped ELF
providers. The original producer remains failed; neither validation rebuilt
GDAL nor reran the JVM. The one-shot evidence validator is local qualification
tooling, separate from this public source builder.

This public recipe adds portable CMake/GCC-helper discovery and the corrected
GNU inventory; it has offline source guards, not a fresh native execution at its
new commit. The original native artifact lineage is retained above. Replacing
the GDAL pair in a newly composed SDK, all six Kernel format categories, complete
renderer behavior and TAKX/server interoperability remain separate gates.
