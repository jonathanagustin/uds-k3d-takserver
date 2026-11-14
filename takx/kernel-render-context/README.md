# Experimental public Kernel render-context source profile

This is a reviewable project source variant of official Kernel **8.30.5**, pinned
to `9f6893dd657feacc35ec5de03dad721c2e44170e`. It implements the observed
RenderContextControl lifecycle used by the pinned TAKX clients. It does not rename
the Kernel, reproduce an unavailable private software development kit (SDK), or qualify rendering/client use.
Graphics processing unit (GPU) context destruction/recreation remains **unqualified**. Binding/font/shader CPU
identities are retained for process lifetime without a fixed bound across unlimited
view/font creation; memory reclamation is not production-qualified.

`prepare.py` is source preparation only. Its default `verify` phase checks this
profile's local patch/contract and starts no process. The explicit `prepare` phase
reads exact blobs from an already cached official Git repository, creates a fresh
**sparse** source projection, and applies these locked stages in order:

1. Official source preimages.
2. The baseline atomic-counter and Java Native Interface (JNI) exception-correctness patches.
3. Frozen TextureFillStyle project patch, reviewed at `ec83eaa0eeed3b37caf57d3cfba0e9850685655b`.
4. This Context patch. Its three batch renderer/shader files overlap Texture, so
   the lock records the actual combined images rather than substituting either
   profile's standalone images.
5. Only the two selected client JNI sections (`interop/feature/Interop.cpp` and
   `jscenelayer.cpp`), not unrelated client Java policies.

Every stage checks all 59 selected paths, including required absence of new files.
`inputs.lock.json` binds original and intermediate/final Secure Hash Algorithm
(SHA-256) images. Baseline
and Texture contracts must match the selected locks. The client profile's full
patch must match its own lock, and its two consumed sections/images must exactly
match this profile; unrelated client Java changes are not silently consumed.
Existing source trees, native artifacts and accepted proofs remain unchanged.

```sh
python3 -B takx/kernel-render-context/prepare.py
python3 -B takx/kernel-render-context/prepare.py --phase prepare \
  --source /path/to/cached-official-git \
  --baseline-profile /path/to/takx/kernel-native \
  --texture-profile /path/to/takx/kernel-texture \
  --client-profile /path/to/takx/kernel-client-interop \
  --output /path/to/new-source-output
```

There is no fetch, compiler, linker, Java virtual machine (JVM) or native-load phase. Source commands have
owned process groups, 20-second command/120-second aggregate deadlines, bounded
streams, a 4 MiB output cap and a 2 GiB free-space floor. Failed output stays
separate and never receives a success receipt.

The output is not a complete native build tree or Java SDK. No native-builder
feature flag is introduced by this profile. A future consolidated builder must
bind these stages and its full original graph, regenerate/merge final Java JNI
headers from actual Context/Texture/client sources, rebuild every changed header
consumer, and audit the resulting libraries. The local qualified composition had
108 affected objects across the original 815-unit graph; that number is evidence
for that exact toolchain/graph, not a portable hard-coded rebuild list.
Production Java, JNI diagnostic probes and state-test doubles must remain separate.
No fake optional library/resource, source omission, version alias or duplicate GDAL
provider is permitted by this source contract.

The current source patch also includes the later checked text callbacks, atlas
binding restoration and optional terrain-attribute guards. All seven updated
source files reproduce byte-for-byte from cached official source and match the
files consumed by the incremental native builds. Those builds preserve the
original context/header composition; they do not replace the full rebuild rules
above.

Local qualification evidence now includes a genuine 108-object/two-library native
variant with static export/NEEDED/TEXTREL/backend-privacy/SQLite-owner checks, plus
five strict real CPU JNI controls. See [QUALIFICATION.md](QUALIFICATION.md) for the
receipt identities and remaining gates. This does not qualify GPU methods, stock
resource packaging, complete legacy JNI coverage, a renderer, or a full SDK/client.
The source ownership and pre-realization reasoning is in [DESIGN.md](DESIGN.md),
[PRE_REALIZATION_AUDIT.md](PRE_REALIZATION_AUDIT.md), and
[TERMINAL_OWNERSHIP_AUDIT.md](TERMINAL_OWNERSHIP_AUDIT.md).

Default continuous integration (CI) runs only these small offline guards; it does not build third-party
sources, acquire dependencies, start Java or open a display:

```sh
python3 -B -m unittest discover -s takx/kernel-render-context -p test_prepare.py -v
```

The separate opt-in CPU worker regression control requires cached official source
and this profile's final prepared source projection:

```sh
python3 -B takx/kernel-render-context/worker_retirement_control.py \
  --official-source /path/to/cached-official-git \
  --prepared-source /path/to/new-source-output/source \
  --output /path/to/new-worker-control --cxx /tools/g++
```

It extracts the production `RetirableWorker` class without edits and compiles it
with all eleven complete official Work/thread/platform/logging/string units and
their verified local header closure. It uses genuine Kernel Work and control
queues; an explicit error delegate checks that real errors are still propagated.
No engine library, JNI, renderer or OpenGL context is built or exercised. The
control runs no source acquisition and cannot qualify the headed lifecycle.
