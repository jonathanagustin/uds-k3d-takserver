# Desktop bitmap slice

This is the bitmap portion of **uds-desktop-android-compat 0.1.0**, a new
repository-local implementation. It is not upstream AndroidPort 6.1.2, an
Android SDK replacement, or a completed Kernel/TAKX runtime. The implementation
is original GPL-3.0-only code using JDK `BufferedImage` and `ImageIO`; no
unlicensed AndroidPort implementation or binary was copied.

## Implemented behavior

- `android.graphics.Bitmap` creates positive-size, straight-alpha `ARGB_8888`
  images. Pixel access and array transfers preserve ARGB bits, including RGB
  bits of fully transparent pixels in newly created images. Both signs of
  stride, offsets, subregions and padding are supported. Checks use long
  arithmetic to avoid integer overflow. Invalid regions/strides throw
  `IllegalArgumentException`; invalid array ranges throw
  `ArrayIndexOutOfBoundsException`; null arrays on nonempty transfers throw
  `NullPointerException`. Zero-area transfers on live, writable images are no-ops without array access.
- The exact reflective `Bitmap(BufferedImage)` constructor and
  `getAwtBufferedImageImplementation()` method retain the caller's actual image
  backing. Mutations remain visible in both directions. An externally supplied
  RGB, indexed or premultiplied image keeps its own color-model limitations;
  wrapping it does not silently convert or promise lossless ARGB storage.
- `BitmapFactory` uses real JDK image readers, converts decoded images to
  straight-alpha ARGB, and returns null for null input, unreadable files,
  unsupported encoded data or decoding I/O failures. PNG is tested. The file
  decoder owns its opened input; the stream decoder starts at the caller's
  current position and never closes the caller's stream. The position afterward
  is wherever the decoder consumed it; no exact trailing-byte position or rewind
  is promised. Its internal memory cache is closed without changing global
  `ImageIO` cache settings.

- `recycle()` releases this wrapper's reference to its backing pixels and is
  idempotent. Pixel reads, writes and marshal unwrapping then fail; metadata
  dimensions remain available. It does not flush or destroy an image still
  owned by a caller or another wrapper. This is reference release, not a
  promise of immediate garbage collection.
- Decodes are immutable by default; `Options.inMutable` requests writable
  pixels. `createBitmap` and the upstream reflective image wrapper remain
  mutable. `inJustDecodeBounds` reads dimensions through the selected ImageIO
  reader without calling its pixel decode and returns null; `outWidth` and
  `outHeight` reset to -1 on an unreadable input. Byte-array decoding respects
  the requested offset and length and rejects invalid ranges before decoding.

The implemented configurations are `ARGB_8888`, `RGB_565` and `ALPHA_8`; see [native pixel layouts](NATIVE-PIXELS.md). Options expose
`inPreferredConfig`, `inMutable`, `inBitmap`, `inJustDecodeBounds`, `outWidth` and
`outHeight`; null uses the same default. The three-argument stream
method accepts a null padding argument (typed `Object`) as used by the pinned
portable factory; non-null padding is explicitly rejected. It is not a binary
replacement for Android's `Rect`-typed method. Scaling, region decoding,
native bitmap handles and other
Android APIs are outside this slice. Fatal JVM resource errors are not converted
to a successful or fabricated image. Untrusted-image memory budgets are not
implemented here.

## Actual upstream contract

Tests consume the official ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`:

- [Portable Bitmap](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/port/src/main/java/gov/tak/api/commons/graphics/Bitmap.java)
  defines the pixel/array exception contracts.
- [Desktop BitmapMarshal](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/port/src/jre/java/gov/tak/api/commons/graphics/BitmapMarshal.java)
  supplies the constructor/method reflection contract.
- [Portable BitmapFactory](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/port/src/main/java/gov/tak/api/commons/graphics/BitmapFactory.java)
  supplies the null/file/stream consumer shape. It currently wraps a null decode
  result without checking it. Thus a failed decode can return a non-null
  portable wrapper whose later pixel access throws `NullPointerException`.
  This upstream wrapper limitation is not fixed or hidden by this implementation;
  low-level decoder null behavior and valid portable decoding are tested separately.

The test compiles the real portable classes, real `BitmapMarshal`, and the real
marshal service/manager/registration chain. The companion PorterDuff slice is
required. The reviewed patch removes only the unused `ColorFilter` import from
`ColorBlendModeMarshal`; no fake class or registry is substituted. The runner
requires the exact source revision, unchanged consumed tracked files, patch
SHA256 `dfafe9c5c670e4a2d62194ac1d6722e1b77b4e94d0d9ec494af6193c88cea2dc`,
and zero-fuzz patch application to a disposable source copy. The upstream
checkout is never patched.

## Local acceptance

Use JDK 17 with the combined compat sources and the reviewed patch present:

```bash
export ATAK_SOURCE_DIR=/path/to/pinned/official/atak
./takx/compat/test-bitmap.sh
```

For separate development worktrees, `TAKX_COMPAT_EXTRA_SOURCE_DIR` may point to
the companion slice's `src/main/java`, and `TAKX_BITMAP_PATCH` to its reviewed
patch file. Both are consumed as sources; no binary SDK is downloaded. The
runner compiles with `javac --release 11`, runs headlessly, and removes its
scratch classes/source copy afterward.

Tests cover alpha, positive/negative padded strides, offset and overflow bounds,
no partial mutation after invalid ranges, PNG/null/malformed/truncated/I/O-error
inputs, caller stream ownership/current position, and actual upstream marshal
backing identity and bidirectional mutation. Passing these tests establishes
this graphics slice only. It does not establish full port/Kernel compilation,
resource catalogs, Context/preferences, SQLite, Android graphics completeness,
map rendering, fonts, CommonCommo routing, or either full TAKX candidate.

## Lifecycle and decoder reference

The added lifecycle, mutability, bounds and byte-array contracts follow
[AOSP Android 14 Bitmap](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Bitmap.java)
and [BitmapFactory](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/BitmapFactory.java).
These are behavioral references, not executable desktop oracles: their native
Android decoder cannot run in this JDK harness. No AOSP implementation is copied.
The tests exercise real PNG data and the unchanged official marshal chain.
The bitmap checks include the previous 51 contracts plus header-only PNG inspection, lifecycle, borrowed-image
survival, independent decodes, immutable writes, bounds reset and byte ranges.

The full-engine diagnostics identify consumers of these APIs, including map
texture cleanup and raster metadata inspection. The unchanged `TerrainRGB`
class additionally needs the complete elevation/geo dependency closure and
native support. This slice does not enable that class, add placeholder dependencies,
or establish full-engine, client, JNI or rendering acceptance. The mutable
image exposed through the existing reflective marshal remains an explicit
borrowed backing view; immutability governs Bitmap writes, not code holding
that external Java2D reference.


## Owned allocation reuse

Images created by this adapter or decoded into it own a packed, straight-alpha
pixel `byte[]` allocation. `reconfigure` changes the logical dimensions by making
a new Java2D raster view over that same array. It does not allocate replacement
pixel storage or clear existing pixels. `getByteCount` reports the current
packed shape; `getAllocationByteCount` reports the original capacity. Positive
dimensions, a mutable live bitmap, and sufficient capacity are required.
Sizes whose byte count cannot fit the Java `int` API are rejected before
allocation. Capacity and argument failures preserve the existing shape/view.
Both byte counts return zero after recycling, as in the referenced AOSP code.

`Options.inBitmap` reuses a mutable owned allocation when the decoded shape fits,
returns the exact same Bitmap object, and leaves it mutable independently of
`inMutable`. ImageIO may still allocate temporary decoding pixels; this is reuse
of the destination allocation, not an allocation-free image decoder. Decode
failure or incompatible byte-array/stream reuse raises `IllegalArgumentException`.
The AOSP file wrapper instead converts an incompatible decode into null; recycled
input validation occurs before that wrapper catches decode errors. A null stream
returns null before reuse validation. In the referenced AOSP Java wrapper,
bounds-only decoding together with non-null `inBitmap` also raises after setting
the output bounds; these semantics are covered explicitly.

Borrowed Java2D images remain a separate storage category. The original image,
including its color model, premultiplication, stride and subimage offset, is
retained. Reconfiguration and byte-count queries on a live borrowed raster
raise `UnsupportedOperationException`; decoding into one raises
`IllegalArgumentException`. This explicit adapter limit avoids inventing an
ARGB allocation capacity for indexed/custom/external storage or silently
converting/detaching it. The AOSP capacity promise is implemented for owned
packed ARGB images, not all arbitrary Java2D layouts.

Existing Java2D views keep their previous dimensions and continue sharing the
owned allocation after reconfiguration. A newly marshaled view reflects the
current dimensions. Callers must stop using old views before reconfiguration;
this corresponds to AOSP's warning about reconfiguring images still in use.
Recycling drops the wrapper's references without destroying separately held
views. The adapter's raster storage is an implementation detail, not a claim
about a complete Android native renderer; the separate [raw byte contract](NATIVE-PIXELS.md) states the supported layouts.

The 239-check harness compiles the unchanged official `ResourcePool` used by
TerrainRGB and the real marshal chain. It exercises pooled return identity,
repeated real PNG decoding, equal-capacity aspect-ratio changes, recovered
capacity after shrink, allocation-array identity, retained storage, invalid
reuse without mutation, immutable/recycled rules, and borrowed RGB/indexed/
premultiplied/subimage ownership. This tests the pool and graphics contracts;
it does not compile or run the complete TerrainRGB/elevation/native dependency
closure. The same AOSP references above define the reconfiguration, byte-count,
and reuse contracts; no AOSP implementation is copied.

The pinned engine consumers motivating reuse are `TerrainRGB.sample`,
`AbstractTilePyramidTileReader` and `SQLiteSingleTileReader.decodeTileBitmap`.
They retrieve candidates from a pool, request mutable decoding, and compare
returned object identity before recycling or returning an unused candidate.
`SQLiteSingleTileReader` also retries after an incompatible-reuse exception.
Only the actual ResourcePool and graphics/marshal chain run in this harness;
those complete tile-reader classes retain other engine/database/native gaps.

Metadata, filtered scaling and PNG/JPEG encoding are documented in [CODECS.md](CODECS.md).
