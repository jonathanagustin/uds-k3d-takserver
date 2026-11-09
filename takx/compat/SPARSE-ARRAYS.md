# Desktop sparse containers

`SparseArray<E>` and `SparseBooleanArray` retain the official AOSP Android 14
algorithms from commit
[`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/util/).
Their original Apache-2.0 notices remain. The full license is in
[LICENSE-Apache-2.0.txt](LICENSE-Apache-2.0.txt); exact official URLs and decoded
source checksums are in [sparse-source.lock.json](sparse-source.lock.json).

The desktop adaptations are explicit:

- Remove Android-only annotations/imports and correct one comment spelling.
- Use standard Java arrays instead of Android's unpadded allocation helpers and
  empty-array singletons. Java array capacity/layout is not an Android VM claim.
- Preserve AOSP's typed growth/insertion algorithms in the package-private
  `SparseArrayStorage`, adapted from `GrowingArrayUtils`; its generic allocation
  uses `java.lang.reflect.Array.newInstance` to preserve component type.
- Use `Arrays.binarySearch(keys, 0, size, key)` for the internally valid ranges.
  It has the same sorted-key index and complemented insertion-point result.
- Always use the documented Android Q+ upper-index exception checks. A desktop
  process has no Android target-SDK switch; legacy undefined-index behavior is
  not offered as a selectable mode.

Deletion/compaction, sorted insertion, append fallback, reference-identity value
search, equality-based search, shallow cloning, content equality/hashing and
boolean-container equality are retained. These containers are not thread-safe;
callers must provide synchronization when sharing them. No empty helper or fake
framework type is introduced.

## Acceptance

The offline harness verifies every locked source hash and compares all adapter
code against the explicit normalization before compiling. It executes the same
contracts against the local classes and an isolated-package copy of the pinned
sources with the same necessary desktop adaptations. It is a source-contract
comparison, not execution inside Android's runtime.

Each variant passes 49,852 deterministic checks. A separate `TreeMap` model
checks randomized sorted keys/values, insertion, replacement, deletion, append
and indexed mutations. Tests also cover negative/extreme keys, stored nulls,
identity versus value searches, clone independence before compaction, range
removal, bounds, self-referential formatting and missing-key defaults. The
assertion count is not a count of APIs or engine compatibility.

```sh
python3 takx/compat/test-sparse.py --aosp-dir /path/to/decoded/aosp/sources
```

The external directory must contain the three exact decoded Java sources in the
lock. The test does not download anything, retains no compiler outputs, and
requires a JDK supporting `--release 11`.

## Actual TAK consumers

At official public ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e`,
`PfpsUtils` keeps frame files in `SparseArray<File>` and `TileScraper` builds a
sorted zoom-level selection in `SparseBooleanArray`. Their complete raster,
GDAL, projection and tile-client dependencies remain separate. These two engine
classes were not compiled or executed by the standalone container test. No
replacement GDAL/terrain classes or native renderer is supplied to manufacture
consumer acceptance. Full Kernel and TAKX 5.7/5.8 acceptance remain pending.
