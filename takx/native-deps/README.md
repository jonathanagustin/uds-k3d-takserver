# Public native dependency profile

This opt-in Linux amd64 recipe builds Draco 1.5.7 from official ATAK source and
verifies TinyGLTF, TinyGLTFLoader and Khronos header inputs. It includes real
codec and PIC-link probes. Full Kernel/JNI, rendering and TAKX client validation
remain separate gates; this profile supplies a dependency, not an SDK.

## Run

Use Linux x86_64, Python 3.9+, GCC/G++ **14.2.0**, GNU `readelf`, CMake **3.31.6**
and Ninja reporting **1.11.1.git.kitware.jobserver-1** (`ninja==1.11.1.4`). Git
must support `--no-lazy-fetch`; Git 2.52.0 was validated. Unsupported tools fail
closed. An isolated CMake/Ninja tool environment can be prepared with:

```sh
uv venv /absolute/path/to/native-tools
uv pip install --python /absolute/path/to/native-tools/bin/python \
  cmake==3.31.6 ninja==1.11.1.4
```

Initialize the existing official gitlink or provide a clean checkout at
`9f6893dd657feacc35ec5de03dad721c2e44170e`, with its complete `draco/` tree
materialized. The build disables implicit Git object fetches.

```sh
GIT_LFS_SKIP_SMUDGE=1 git submodule update --init upstream/atak-civ

python3 takx/native-deps/build.py \
  --source upstream/atak-civ \
  --output /absolute/path/to/new-native-dependency-proof \
  --cache /absolute/path/to/native-source-cache \
  --cmake /absolute/path/to/native-tools/bin/cmake \
  --ninja /absolute/path/to/native-tools/bin/ninja \
  --jobs 1 \
  --fetch-dependencies
```

`--fetch-dependencies` permits only the official URLs in
[inputs.lock.json](inputs.lock.json): two modified source archives and eleven
headers. Downloads match locked SHA256/size identities; Khronos files also match
Git blob IDs. Omit the flag for offline operation with a populated verified cache.
Corrupt inputs are refused, and another invocation's partial files are preserved.

Output and cache must be separate, outside the repository. Output must be new;
a failed or completed directory is never adopted. The default is one build job,
with two available explicitly. Compilation has a 20-minute ceiling; other
commands have bounded output/time and owned-process cleanup. Ambient compiler
flags and CMake hooks are ignored. Observed staging used about 85 MB of source
plus less than 200 MB for this dependency build and outputs, excluding tools.
Default server tasks do not run it; CI runs only its offline guards.

## Proof and provenance

All **984** Draco files are frozen after checking their pinned Git tree/blob
identities. Modified, ignored/untracked or nonregular native inputs are refused.
Source, recipe and probe bytes are rechecked after compilation. Selected archive
headers/licenses are copied only after exact hash, path and regular-file checks.
Duplicate members and symlinks cannot replace them.

The unchanged upstream build produces a PIC static codec, encoder and decoder.
Full upstream tests and the optional transcoder are disabled. The real
`cube_att.obj` fixture is encoded and decoded; a separate C++ consumer checks
12 faces, three attributes, eight geometric corners and truncated-data rejection.
A whole-archive shared link checks the static library for TEXTREL. Its output is
named `libdraco-pic-check.so`, with no Kernel library replacement or client link.

TinyGLTF 2.4.1 and TinyGLTFLoader 0.9.5 retain their original include layouts.
Their licenses/README attribution and packaging recipes, Draco's Apache license,
and original header notices are retained. `complete.json` records tools, source
and recipe identities, installed hashes/license receipts, and explicit hashes
for the consumer, PIC probe and codec outputs. `sources.json`, frozen sources,
logs and all actual probe outputs remain in the external proof directory.

These hashes establish local integrity, not signed provenance, bit-identical
builds or a dependency security assessment. Host libraries are not a hermetic
closure. GCC 14.2 host PIC success does not establish a future TAKX image's
glibc/libstdc++ ABI or reproduce the upstream Conan target ABI; actual target
compilation and image linkage remain required.

## Checks

Run guards for input tampering, archives, source export, offline Git behavior
and command bounds without downloading or compiling:

```sh
python3 -B -m unittest discover -s takx/native-deps -p test_build.py -v
```

After a genuine completed build, run the real codec/PIC regression without
rebuilding:

```sh
TAKX_NATIVE_DEPS_PROOF=/absolute/path/to/completed-proof \
  python3 -B -m unittest discover -s takx/native-deps -p test_build.py -v
```

It verifies receipt/output hashes before execution, checks the real consumer,
requires upstream decoder rejection of an externally truncated stream, and
inspects the PIC link. Without a proof, that one integration test is skipped.

## Next native dependencies

The official [CMake requirements](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/engine/CMakeLists.txt)
use a credentialed Conan default, but public source exists for seven of eight
direct package families. Source availability still needs full build/API checks.
The remaining profile includes `ttp-dist/4.2.4`, public modified `libLAS/1.8.2f`
and `cesium-native/0.40.1`. The [TTP Makefile](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takthirdparty/Makefile)
supports `GDAL_USE_KDU=no`; MrSID supports `mrsid_BINBUNDLE=disabled`. State
omitted optional drivers explicitly, then validate GDAL, Spatialite, Assimp,
LAS, PDFium and the remaining closure.

Official Cesium v0.40.1 resolves to
[`f8b38abbbaa24ec2984ff663182240d06285b36c`](https://github.com/CesiumGS/cesium-native/tree/f8b38abbbaa24ec2984ff663182240d06285b36c)
and selects public vcpkg 2024.07.12 dependencies. Its source build and exported
API/library compatibility with TAK's wrapper remain unverified. The checked
public source scope did not supply `GLES-stub/2.0.0`; an explicit Linux profile
can investigate real Mesa without relabeling it as that package.

A separate Mesa EGL 1.5/GLES 3.2 llvmpipe pixel-readback probe established host
headless GL capability, not Kernel rendering. Native style primitives likewise
do not establish JNI behavior; upstream composite equality uses component
pointer identity. Remaining gates include full Kernel/JNI, polygon UV/shaders
and resource lifecycle, offscreen rendering with holes, map recovery,
[textured fill](https://github.com/jonathanagustin/uds-takserver/issues/424),
complete 5.7/5.8 client compilation/resources and live interoperability.
