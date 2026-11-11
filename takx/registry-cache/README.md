# Experimental local Draco cache

Package a verified Draco 1.5.7 producer into a small relocatable component. This
is the local foundation for [#482](https://github.com/jonathanagustin/uds-takserver/issues/482).
It does **not** publish to a registry, authenticate a publisher or qualify a
complete SDK. Existing native profiles and CI defaults remain unchanged.

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
Untrusted PRs must remain read-only. No signing grant or workflow token changes
are introduced here.

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
`python3 -B -m unittest discover -s takx/registry-cache -p 'test_*.py' -v`.
