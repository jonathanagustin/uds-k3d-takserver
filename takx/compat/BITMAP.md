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
  `NullPointerException`. Zero-area transfers are no-ops without array access.
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

The only declared configuration is `ARGB_8888`. Options expose only
`inPreferredConfig`; null uses the same default. The three-argument stream
method accepts a null padding argument (typed `Object`) as used by the pinned
portable factory; non-null padding is explicitly rejected. It is not a binary
replacement for Android's `Rect`-typed method. Scaling, region decoding,
recycling, compression, canvas operations, native bitmap handles and other
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
