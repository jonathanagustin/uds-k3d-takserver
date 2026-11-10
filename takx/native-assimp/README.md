# Public Assimp native profile

Build the official modified Assimp core, zlib and matching Java/JNI bindings.
The opt-in Linux amd64 recipe checks ordinary geometry, materials, transforms,
UVs and normals through genuine C++, C and Java APIs. Full Kernel/JNI, rendering,
TAKX and target-image ABI validation remain separate gates.

A fresh local entrypoint build and its explicitly enabled real fixture test
passed, with zero JVM JNI warnings.

## Run

Use Python 3.9+, GCC/G++ **14.2.0**, CMake **3.31.6**, GNU patch/nm/readelf and
Ninja reporting **1.11.1.git.kitware.jobserver-1** (`ninja==1.11.1.4`). Provide a
verified official Eclipse Temurin **17.0.21+9** JDK. Its release asset/checksum
reference is in [inputs.lock.json](inputs.lock.json); tool installation stays
separate. The recipe checks versions and freezes the supplied SDK's bytes/links.

```sh
python3 -B takx/native-assimp/build.py \
  --output /absolute/path/to/new-assimp-proof \
  --cache /absolute/path/to/assimp-source-cache \
  --jdk-home /absolute/path/to/verified-temurin-17 \
  --cmake /absolute/path/to/native-tools/bin/cmake \
  --ninja /absolute/path/to/native-tools/bin/ninja \
  --fetch-dependencies
```

Only `--fetch-dependencies` permits downloads, from the two exact official URLs
in the lock. Without it, the recipe requires a populated verified archive cache
and runs offline. SHA256/size checks refuse missing or corrupt cache entries;
other invocations' partial files are preserved.

Output must be new, outside the repository and separate from cache and SDK.
Failed outputs are never adopted. One build job and bounded logs/process groups
apply throughout, with a 20-minute core ceiling and three-minute JNI ceiling.
Output plus cache is checked against a 12 GiB cap between stages. The validated build
and archive cache used about 0.8 GB; the supplied JDK needs additional space.
Compiler/CMake/Conan/Java injection variables and binary caches are ignored.
No normal server task or CI job builds this profile.

## Sources and changes

Both source archives come from
[official ATAK commit 9f6893d](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).
The archive is named **assimp-4.0.1-mod**, while its modified source/library reports
**4.1.0**, SONAME **4**. Zlib is **1.3.1**. Preserve those distinct identities.

The CMake-only project patch requires actual static zlib headers/library inside
the verified prefix, uses genuine bundled unzip/IrrXML/OpenDDL/Open3DGC sources,
and separates the one-TU JNI build from the core. All 47 default public importer
flags and exporters remain enabled; non-free C4D stays disabled, as upstream.
Tools, samples, docs and upstream tests are disabled for this bounded slice.

The JNI project patch checks pending exceptions around three Java-call helpers,
preserves exceptions in metadata returns and at the import boundary, and returns
no partial scene on failure. It changes no public headers, Java classes, layout
or native signatures. Runtime failure-path behavior is not accepted by the
ordinary positive controls.

Archive extraction locks member/file/expanded-byte counts and refuses duplicate,
nonregular or escaping paths. All source and patch pre/postimages are frozen;
only zlib's known byte-preserving zconf.h rename is allowed during configuration.
Nine selected, verified original notices are copied under install/licenses; the
full source inventory retains other bundled notices. This is not a complete
license or security assessment.

## Verify

Offline guards need no tools, downloads or native build:

```sh
python3 -B -m unittest discover -s takx/native-assimp -p 'test_build.py' -v
```

After a fresh entrypoint build, enable its real fixture explicitly:

```sh
TAKX_NATIVE_ASSIMP_PROOF=/absolute/path/to/new-assimp-proof \
  python3 -B -m unittest discover -s takx/native-assimp -p 'test_build.py' -v
```

The real test skips when the variable is unset and refuses receipts from older
manual builds or changed recipes. It checks output/source/SDK/runtime identities
before re-executing the ordinary Java/JNI fixture.

The build checks actual COLLADA import and assbin export/reimport, separate
C-compiled scene/material/matrix calls, 42 matching Java sources, 10 native
signatures and exact mapped library/JAR paths. `-Xcheck:jni` must emit zero
warnings. Strict shared links and whole-archive static PIC checks refuse TEXTREL.
The modified IrrXML archive needs Assimp logger symbols, so its PIC probe links
the exact verified core DSO and checks that dependency's SONAME, path and hash.
`complete.json` binds recipe, sources, tools, outputs and runtime provenance.

No malformed-input, injected-failure, full upstream-suite or general security
acceptance is implied. Full TTP, modern dependency/version assessment, target
libstdc++/glibc ABI, Kernel/JNI, GL/TextureFill and TAKX runtime remain open.
