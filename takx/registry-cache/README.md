# Experimental local Draco cache

Local commands package a verified Draco 1.5.7 producer into a small relocatable
component, the foundation for [#482](https://github.com/jonathanagustin/uds-takserver/issues/482).
These commands do **not** publish to a registry, authenticate a publisher or
qualify a complete SDK. Existing native profiles remain unchanged. The separate v2 manual
workflow below adds an optional trusted publisher; ordinary PR CI does not build
or publish native components.

The payload contains the real static archive, 201 installed Draco headers, four
upstream CMake package files and the upstream license. It excludes executables,
other components, the non-relocatable `draco.pc`, fixtures, logs and databases.
Original producer sources, tools, installed outputs and codec/PIC proofs are
checked before projection; the new capsule has its own receipt contract.

```sh
python3 takx/registry-cache/draco.py pack \
  --producer /verified/draco-producer \
  --producer-receipt-sha256 <reviewed-complete-json-sha256> \
  --output /new/draco.tar.gz

python3 takx/registry-cache/draco.py restore-local \
  --capsule /verified/draco.tar.gz --sha256 <capsule-sha256> \
  --input-key <local-v1-key> --output /new/restored-component
```

The caller pins both the capsule digest and input key from a reviewed local
producer. Verification checks every allowlisted file, rejects links, duplicate
paths/JSON keys and traversal, and bounds compressed/decompressed bytes before
parsing extended tar headers. Limits are 16 MiB compressed, 32 MiB payload,
1,000 files and 2 MiB JSON. Restore never executes CMake or native code and never
overlays an existing directory. The tar/gzip metadata is deterministic.

The key binds the original source tree/inventory, applied patches (none), consumed
recipe/tool identities, actual configure command and generated build metadata,
plus the projection recipe. README and test-only changes do not enter the key.
Original producer paths remain in these exact inputs: this experimental key does
not claim identical results across different build roots.

The old producer did not record a pinned build image, complete target ABI,
compiler backend or binutils identity. Those fields remain explicitly unknown;
current observations cannot replace historical evidence. The contract therefore
refuses registry-qualified or SDK-accepted capsules. A future registry consumer
needs complete target/tool/environment identity, immutable dependency digests,
verified protected-workflow provenance and a separate trusted writer policy.
Untrusted PRs must remain read-only. The local commands introduce no signing
grants or workflow token changes.

## Local relocation controls

```sh
python3 takx/registry-cache/qualify.py \
  --capsule /verified/draco.tar.gz --sha256 <capsule-sha256> \
  --input-key <local-v1-key> --fixture /verified/draco-producer/cube.drc \
  --output /new/relocation-proof --cmake /tools/cmake --ninja /tools/ninja \
  --cxx /tools/g++
```

This opt-in check restores two unrelated prefixes, constrains the genuine
`draco::draco` target to each prefix, rebuilds the unchanged codec fixture control
and whole-archive links the actual static library with strict PIC/undefined-symbol
checks. It records actual initialized system providers and rehashes payloads.
These are current local relocation observations, not historical producer evidence
or a registry push/pull test. It does not rebuild Draco.

Run offline guards with
`uv run --no-project --with pyyaml==6.0.3 python -B -m unittest discover -s takx/registry-cache -p 'test_*.py' -v`.

## Fresh registry producer (v2)

`native-cache.yaml` is a separate manual workflow, restricted to main. Publishing
is off by default. Its first job builds genuine Draco from the pinned official
Git tree inside a pinned GCC image with network access disabled and no job
credentials mounted. Before and after compilation it binds actual compiler
backends, binutils, build tools, source and provider identities. It records the
complete archive closure and real fixture/roundtrip/PIC controls.

```sh
python3 takx/registry-cache/producer.py build \
  --source /official/pinned-checkout --output /new/fresh-producer \
  --cache /verified/tool-cache
```

The fresh v2 schema and `registry-v2-*` key never upgrade old local receipts.
Only the dependent publisher job receives package/signing grants. It stages an
immutable OCI subject, signs publisher provenance and explicit native
qualification, verifies both against the exact repository/workflow/main/source,
and reads the subject back without registry credentials. Two new prefix
consumers must pass before the key tag is promoted. A different subject for an
existing key fails closed. No PR or scheduled writer is introduced.

The reader requires an explicitly approved producer source SHA; it does not
trust a source revision merely because unsigned metadata names it. A read-only
PR consumer can use that reader later; no automatic PR restore is wired here.
No authenticated registry specimen has been qualified yet. The first hosted
experiment remains required before #482 can close.

A newly created GHCR package can be private even when its source repository is
public. Anonymous readback deliberately fails until its package visibility is
public; registry credentials are never a fallback. If the first publication
stops there, change the package visibility, confirm anonymous access, then rerun
only the failed publisher job in the same run. Its successful build artifact is
retained, so this recovery does not rebuild the native component. A run started
with publishing disabled cannot enable its skipped publisher through a rerun.

The workflow caps build/publication jobs at 12/8 minutes. Local producers refuse
a small Docker `vfs` workspace before pulling: the pinned eight-layer GCC image
exhausted a workspace with 7 GiB free before a container could execute. At least
12 GiB free is required with `vfs` (3 GiB for other drivers). The owned image was
removed after that failed feasibility check; no fresh native build was claimed.
Source-tree validation, pinned CMake acquisition and offline guards passed.

Build failures retain only complete command logs with observed exit status and
matching size/hash records. The failure-only sanitizer redacts each entire
stream before upload; it omits interrupted, oversized, unrecorded or
unsanitizable captures. These diagnostics never count as native qualification
and contain no recorded command argument vectors. The first hosted attempt
failed before producing a candidate; its private inner log was not retained,
so its precise container failure remains unknown.

Independent source review found that GCC backends silently accept `--version`
without reporting identity. Backend metadata now uses genuine `-version` with
quiet, syntax-only and explicit null input/output controls. Local GNU 14.2
metadata probes produced repeatable nonempty identity and no assembly files;
this is not a pinned-container build qualification or proof of the lost job's
specific inner failure. The exact version command enters each tool identity.
