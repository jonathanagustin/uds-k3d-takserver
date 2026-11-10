# Public LAS native profile

Build libLAS, LASzip and their Boost dependencies from official public ATAK
source archives. The opt-in Linux amd64 profile checks real LAS/LAZ reads,
compressed cursor behavior, error handling and PIC linking. Full Kernel/JNI,
rendering, TAKX and target-image ABI validation remain separate gates.

## Run

Use Python 3.9+, GCC/G++ **14.2.0**, GNU patch/readelf and CMake **3.31.6**.
Ninja must report **1.11.1.git.kitware.jobserver-1** (`ninja==1.11.1.4`). Prepare
isolated tools if needed:

```sh
uv venv /absolute/path/to/native-tools
uv pip install --python /absolute/path/to/native-tools/bin/python \
  cmake==3.31.6 ninja==1.11.1.4

python3 takx/native-las/build.py \
  --output /absolute/path/to/new-las-proof \
  --cache /absolute/path/to/las-source-cache \
  --cmake /absolute/path/to/native-tools/bin/cmake \
  --ninja /absolute/path/to/native-tools/bin/ninja \
  --fetch-dependencies
```

Only `--fetch-dependencies` permits downloads, from the two exact official URLs
in [inputs.lock.json](inputs.lock.json). Without it, the recipe requires a
populated verified cache and runs offline. SHA256 and size checks refuse corrupt
inputs. Cache entries are named by their locked SHA256; unrelated partial files
are preserved.

Output must be new, outside the repository and separate from cache. A failed
output is never adopted. The recipe uses one build job, a 20-minute ceiling per
build stage, bounded logs/process groups and a 12 GiB output-plus-cache ceiling
checked between stages. Allow at least 2 GiB free disk. The validated build and
141 MB archive cache used about 0.9 GB; separate diagnostics need extra space.
Compiler/CMake/Conan overrides and external binary caches are ignored. Normal
server tasks and CI do not build these libraries.

## Sources and patches

The [locked archives](inputs.lock.json) come from
[official ATAK commit 9f6893d](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e/depends).
The libLAS archive includes genuine Boost 1.77 sources. Static PIC LASzip and
Boost builds feed strict libLAS shared links; canonical prefix checks and audited
link commands refuse host-library fallback. GDAL/GeoTIFF and optional Boost
compression filters stay disabled in this dependency slice.

Four small patches have separate provenance:

- Project CMake integration replaces unconditional Conan resolution with explicit
  source-built Boost/LASzip prefixes.
- Five LASzip decoder-initialization checks are backported from
  [official commit a446a0c](https://github.com/LASzip/LASzip/commit/a446a0c01362ed1c642928cff30416217f0468c3).
  Other changes in that commit are excluded.
- A project libLAS cursor fix gives the compressed decoder ownership of stream
  positioning and checks reset/seek failures.
- A project C API fix returns failure after an already-reported seek exception.

No public headers, API or class layout change. Failed operations can still alter
stream/decoder state; the patches do not implement transactional rollback.

Source archives are extracted with exact file/member/expanded-byte counts,
regular-file restrictions and duplicate/path checks. Patch preimages/postimages
and all source files are hash-bound before and after the build. Only four known
Boost bootstrap outputs and libLAS's generated README may be added; their bytes
are also frozen. License files and original notices are retained in the install.

Preserve upstream identities: libLAS package **1.8.2f**, CMake **1.8.2b1**, API
**1.8.2**, SONAME **3**, library file **2.4.0**; LASzip package **3.4.3c**, API
**3.4.3**. Their different version strings are present in the official sources.

## Verify

Offline guard tests run without tools, downloads or builds:

```sh
python3 -B -m unittest discover -s takx/native-las -p 'test_build.py' -v
```

After building, explicitly enable the real fixture test:

```sh
TAKX_NATIVE_LAS_PROOF=/absolute/path/to/new-las-proof \
  python3 -B -m unittest discover -s takx/native-las -p 'test_build.py' -v
```

The real test skips when the variable is unset. It checks recipe/output hashes
before executing the consumer. The build's `complete.json` records source,
patch, tool, installed-library, loaded-runtime and probe identities.

The fixture checks three nontrivial format-3 points through C++ and C APIs,
including scale/offset, GPS time, color, classification and returns. It exercises
sequential reads, seek 0/2/0, Reset after partial reads and EOF, ReadPointAt,
out-of-range errors and recovery. The immutable malformed LAZ reproducer must
return zero points and explicit read/seek errors. Whole-archive shared linking
checks all static dependencies for PIC/TEXTREL. ASAN/UBSAN instrument the consumer;
the vendor libraries themselves are not instrumented.

Known limit: uncompressed LAS truncated to one payload byte can return one
partial point before EOF. This profile does not establish general malformed-file
safety. Host GCC PIC proof also leaves target glibc/libstdc++/Conan ABI acceptance
open. Full TTP, Cesium and remaining native dependencies, Kernel/JNI linking,
GL rendering/TextureFill and an actual TAKX client remain separate work.
