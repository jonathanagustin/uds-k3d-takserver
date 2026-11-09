# Desktop LruCache and resource lifetime

This slice adds the actual `android.util.LruCache<K,V>` contract to
`uds-desktop-android-compat`. It is an explicitly named desktop source adapter,
not an Android SDK artifact, a renamed upstream version or a completed TAKX app.

## Source and license

The source is official AOSP Android 14 commit
[`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/util/LruCache.java).
The decoded Java source SHA256 is
`a967489ecde0bdab05af1d2e1b55258f8e6762065cd48200a45f5733d2514995`.
The URL, revision, checksum and adaptation are recorded in
[lru-source.lock.json](lru-source.lock.json). The original AOSP copyright and
Apache-2.0 notice remain, with the existing complete
[Apache-2.0 license](LICENSE-Apache-2.0.txt).

Two desktop adaptations are applied explicitly:

- Remove Android's `UnsupportedAppUsage` annotation and its import.
- Replace Android's `LinkedHashMap.eldest()` extension with
  `map.isEmpty() ? null : map.entrySet().iterator().next()`. This expression
  runs under the same original cache monitor and returns the same oldest
  access-order entry, including the empty-map case.

All remaining Java source, including cache algorithms, synchronization and
callback ordering, matches the pinned source exactly. The test script checks
that equality before compilation and refuses a mismatched source checksum.
It also runs the same contract tests against the actual pinned source in an
isolated package, with these same necessary JVM normalizations. This is a
source-contract comparison, not execution inside Android's runtime.

## What is tested

The dependency-free Java tests cover access-order eviction, statistics and
hit-rate formatting, snapshot independence, weighted sizes, invalid sizes,
inconsistent mutable sizes, zero-weight entries, resize and evictAll. Real
file-backed `FileChannel` resources test replacement, removal, 32-entry eviction
and final cleanup without double closure. Deterministic latches exercise a
create/put race and two simultaneous creators; discarded created resources must
close while the winning cached resource stays open. Blocked callbacks permit
other threads to access the cache.

`create` and `entryRemoved` are invoked without a monitor acquired internally
by the cache around those callbacks. A caller that explicitly synchronizes on
the cache still holds its own monitor, as the AOSP documentation permits; the
adapter does not release a caller's external lock. Size accounting remains
inside the cache monitor. Resource ownership is supplied by the consumer's
`entryRemoved` override, not automatic copying or reference counting.

## Actual TAK consumer and limits

At official public ATAK revision
[`9f6893dd657feacc35ec5de03dad721c2e44170e`](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/engine/src/main/java/com/atakmap/map/formats/srtm/SrtmElevationSource.java),
`SrtmElevationSource.TileSource` creates a 32-entry
`LruCache<String, ElevationChunk>`. Its `entryRemoved` calls `oldValue.dispose()`;
its cache insertion uses `ElevationChunk.Factory.makeShared` to retain a separate
reference. The source SHA256 is
`1fcb87ff6573337a0aaa0ecb5cfa40696a19f30b5ef6b37ae11bb10d4d67a8d2`.

The tested file resources demonstrate real resource lifetime for the cache
callbacks. They do not stand in for `ElevationChunk`, its shared references,
GDAL datasets or native terrain loading. SRTM's actual consumer also imports
GDAL, native elevation/geometry, IOProvider and tiled-source infrastructure;
this bounded slice does not compile or run that full dependency graph. Other
public consumers include `FeatureStyleParser` and `CachingFeatureDataStore`;
the former initializes native Style interop. No replacement classes or fake
JNI resources are supplied to manufacture consumer acceptance.

## Reproduce locally

Fetch the locked public URL and base64-decode its `format=TEXT` response into an
external cache file. With a JDK supporting `--release 11`, run:

```sh
python3 takx/compat/test-lru.py --aosp-source /path/to/decoded/LruCache.java
```

The test itself is offline, writes compiler outputs to a temporary directory,
and performs no engine/native build or workflow dispatch. The observed local
run passed 132 assertions for each source variant. The existing complete public
Kernel port compile and its 19 runtime checks also passed with this adapter
included; native rendering and full TAKX acceptance remain unproven. Both
requested official TAKX 5.7 and 5.8 profiles remain candidates, with 5.8 preferred
only when actual compile/runtime evidence supports it.
