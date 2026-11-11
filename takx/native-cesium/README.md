# Public Cesium Native source graph

This opt-in Linux profile prepares genuine Cesium Native 0.40.1 and its public
static dependency graph from pinned archives and the pinned vcpkg 2024.07.12
port recipes. It does not invoke vcpkg, private Conan, or automatic downloads
from CMake. It retains all eighteen upstream Cesium library targets.

The selected SQLite API provider is actual SQLCipher 4.5.7 (SQLite 3.45.3),
not vcpkg SQLite 3.46.0. Crypto is actual OpenSSL 3.5.9, not the stock vcpkg
3.3.1. Draco 1.5.7 is reused only after its sources, installed inventory,
toolchain, recipe and codec/PIC controls are verified. These identities remain
explicit. CommonCommo's distinct quictls ABI is not qualified by this profile.

Acquire with `acquire.py --output <new-external-output> --cache <owned-cache>
--sqlcipher-proof <producer> --draco-proof <producer>`. Cached archives require
published SHA512 verification (Cesium is checked against its complete pinned
Git blob tree). Build with `build.py --sources <acquisition-output> --output
<new-external-output> --sqlcipher-proof <producer> --draco-proof <producer>`.
Both commands refuse output overlap and preserve failures. Bounds are 512 MiB
compressed, 4 GiB expanded including reused sources, 6 GiB build output, one
job, 180 s configure and 1800 s per compilation stage. Output/log limits kill
the owned process group. No host package installation is performed.

Three packages install verified headers directly. Other packages use genuine
upstream CMake targets and exports. NASM is not
installed: libjpeg-turbo uses its genuine portable implementation with
`WITH_SIMD=OFF`; JPEG format support is retained. KTX uses the exact pinned
port feature selection, including its codecs/transcoder, without Vulkan
upload and tools. Runtime/source patches are the original pinned port bytes.

The only Cesium packaging changes select the explicit public prefix instead
of the ezvcpkg/toolchain layout and link the real `SQLCipher::SQLCipher` target.
No Cesium C++ source, target, or algorithm is removed. `providers.cmake` creates
an imported target backed by the actual SQLCipher archive and verified OpenSSL
product. A parent project includes it and uses `add_subdirectory` for the
patched upstream source; upstream does not provide an installed Cesium EXPORT.
Static transitive dependencies follow the genuine target graph rather than a
handwritten archive order.

Archive links are refused except explicitly attested KTX license and zstd
CLI test fixtures, which are materialized to exact same-root regular target
bytes and recorded with logical source-link metadata and postimage hashes.
This does not execute those test wrappers.

A local interrupted producer may be continued only with `--resume` and its
complete `--snapshot` file inventory. Every stopped source, installed product,
configuration, object and log is rehashed before any copy; tools, provider and
acquisition identities and completed action order must match. The stopped tree
stays unchanged, and receipts retain both recipes and explicit
`fresh_dependency_build=false`. This is local producer lineage, not protection
against a hostile metadata author or a portable binary cache.

A complete eighteen-target build does not establish full Kernel, JNI, client,
renderer, SDK assembly, process-wide crypto coexistence, or format behavior.
Those require later genuine full targets and consumer tests.

## Recorded build

The recorded local producer built all eighteen archives from 173 distinct
production translation units. Its dependency build was explicitly resumed;
the Cesium compilation was fresh. The original stopped tree and frozen producer
remain separate from later guard and copied-metadata relocation improvements.
Those later changes passed offline guards; they are not presented as a new
complete source build. Nine unused original-prefix pkg-config files remain a
limitation of the historical output; its actual CMake graph uses the verified
relocated providers. No general portable-prefix acceptance is claimed.
