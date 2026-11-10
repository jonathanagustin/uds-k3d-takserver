# WorldWind Java from public source

This recipe builds a project-identified Java artifact from NASA WorldWind
v2.2.1, including its examples, resources and upstream license notices. It does
not recreate `gov.nasa:worldwind:2.2.1-TAKX-4`, whose patch set has not been
established, or establish a working TAKX application. No native code is built or
loaded. Native GIS/GL/Kernel linkage and rendering remain separate blockers.

The pinned source is [NASAWorldWind/WorldWindJava](https://github.com/NASAWorldWind/WorldWindJava/tree/9ccf6b8ed2ae452ef51e7b1739a7ffd4ef78a403),
commit `9ccf6b8ed2ae452ef51e7b1739a7ffd4ef78a403` (v2.2.1). The lock records all
1,726 Java files and all other tracked `src/` resources. Examples are included:
TAKX imports them. The source checkout must match every consumed byte and have
no untracked source/resource files. NASA's missing NetBeans build include is not
needed by this explicit compiler recipe.

## Explicit project profile

Unchanged NASA source fails against the source-built public GDAL 2.4.4 bindings:
`gdal.LibraryLoader`, `gdal.setLibraryLoader` and
`ColorTable.getIndexColorModel(int)` are absent (four compiler diagnostics).
`standard-gdal.patch` defines the **project-standard-gdal-rgb** profile:

- Remove NASA's optional custom loader replacement. The real `initialize()` and
  `gdalPreLoadNativeLibrary()` paths remain. This is not a loader implementation
  or a native compatibility guarantee; standard GDAL JNI loading still needs
  valid libraries at runtime.
- Convert RGB palette entries through the real public `GetCount()` and
  `GetColorEntry()` methods. The pinned source's
  `swig/include/java/typemaps_java.i` returns packed ARGB integers in both
  branches, despite its stale J2SE `java.awt.Color` comment. The project helper
  preserves alpha and 1–16-bit palette indices using BYTE/USHORT transfer types.
  The exact GDAL archive URL, SHA-256 and upstream pin are recorded in
  [the GIS source lock](../gis-java/sources.lock.json); no SDK binary is used.
  Non-RGB palettes fail explicitly; they are outside this profile. Native GDAL
  behavior is not tested by the pure Java conversion tests.

The compilation includes 1,725 unchanged upstream Java files, one patched
upstream file (`GDALUtils.java`), and one project helper. Both the patch and helper are hash locked. This profile changes upstream source;
it must not be presented as unmodified NASA or the private TAKX variant.
NASA's Apache license and included third-party notices are retained in the JAR;
the project helper retains its GPL-3.0-only header. The combined project variant
is GPL-3.0-only and includes the hash-verified project `LICENSE` alongside the
NASA and third-party notices; it is not labeled as an Apache-only artifact.

## Local build

Requirements: Python 3.11+, Git, JDK 17, a pinned official NASA checkout, verified
JOGL/gluegen 2.5.0 JARs from their official URLs in the lock, and a current
[source-built GIS output](../gis-java/README.md). No input is downloaded here.
The GIS receipt and exact reviewed class inventory are checked before compiling.

```sh
python3 takx/worldwind-java/build.py \
  --source /path/to/WorldWindJava \
  --public-jars /path/to/official-java-jars \
  --gis-build /path/to/verified-gis-build \
  --output /path/to/new-worldwind-output
```

Outputs include copied verified source, compiler diagnostics, input/output
receipts and, only on complete compiler success,
`uds-takserver-worldwind-java.jar`. JAR entries are sorted with fixed timestamps
and permissions. The receipt captures source, recipe, project patch, dependency,
compiler binary path/hash, exact command and GIS receipt identities. Dependencies
are rehashed after compilation before packaging. Compiler timeout (240 seconds)
retains stdout/stderr and an explicit failure receipt while removing partial output. Failed builds retain diagnostics and remove
partial class output; they never produce a JAR. Output directories must be new.

## Checks and limits

Normal Unit CI runs offline integrity, deterministic archive/resource lookup and
pure Java palette tests. It does not download dependencies or compile WorldWind.
The pure Java test loads only the standalone project helper, never GDALUtils or
JNI. It covers transparent ARGB, 1/8/9/16-bit indices, 65,536-entry palette raster
lookup, and rejected invalid depth/count values.

The full-source integration test is opt-in and uses local inputs:

```sh
WORLDWIND_SOURCE=/path/to/WorldWindJava \
WORLDWIND_PUBLIC_JARS=/path/to/official-java-jars \
WORLDWIND_GIS_BUILD=/path/to/verified-gis-build \
python3 -m unittest discover -s takx/worldwind-java -p test_build.py -v
```

This build is a compile checkpoint. It does not validate TAKX's complete member
API use, full dependency closure, application packaging, GUI, imagery drivers,
enrollment, networking or CoT interoperability.

Blacksmith scope was checked against official TAKX
[5.7](https://github.com/TAK-Product-Center/TAKX/tree/0b59a9bb2d0e90dc35c9edfff1c2056daab2b713)
and [5.8](https://github.com/TAK-Product-Center/TAKX/tree/af54a3e1fe8796b6e109e2e5925dbef524ea7e31):
`gradle/standardTestSetup.gradle`, `TestSupport/build.gradle` and root
`build.gradle` establish a test-suite dependency, not a production runtime gap.
Its source implementation remains unestablished by this work.
