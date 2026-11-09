# Owned pixel formats and raw ByteBuffer copies

Owned Bitmap storage is now one canonical `byte[]` allocation, shared directly
by its Java2D raster views. Current row bytes and pixel byte count depend on the
configuration; allocation byte count remains the actual original array length.
Cross-configuration reconfiguration retains that array and reinterprets bytes
without clearing them. Old views retain their dimensions and interpretation;
callers must stop using them before reconfiguration.

| Configuration | Actual tight-row storage | Semantic pixel conversion |
| --- | --- | --- |
| ARGB_8888 | R, G, B, A bytes | Straight, unpremultiplied channels |
| RGB_565 | Little-endian 16-bit R5G6B5 words | Rounded low-precision CPU packing; bit-replicated unpacking; opaque |
| ALPHA_8 | One alpha byte | RGB ignored on writes and zero on reads |

The owned default is **unpremultiplied**, preserving the adapter's existing
straight-alpha pixel and PNG contracts, including transparent RGB values.
This differs from Android's default premultiplied Bitmap creation. Actual
premultiplied storage would quantize low-alpha RGB and cannot preserve those
existing values. `isPremultiplied()` reports false for owned images;
`setPremultiplied(false)` accepts their real current state. Requesting true is
explicitly unsupported; no hidden conversion or interpretation change occurs.
Borrowed images report their actual Java2D premultiplication model.

The desktop Canvas accepts this straight-alpha storage through Java2D; Android
Canvas restrictions on drawing unpremultiplied source images are not reproduced.
ALPHA_8 is genuine alpha-only storage, including drawing into it. Drawing an
ALPHA_8 source without tint uses its black/alpha semantic pixels. Nonblack
Paint tint for an alpha-only bitmap source is explicitly unsupported.

## Native evidence and supported copy contract

Pinned source URLs and hashes are in `bitmap-native-sources.lock.json`:
AOSP framework base `299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368` and Android
14 Skia `1145116447a46710a65e3a5deabb7d7c752af5ea`.

- Bitmap.java documents raw copying as-is, including premultiplication, and
  advances Buffer positions by the copied element count.
- Native Bitmap.cpp uses memcpy of `bitmap.computeByteSize()` in both copy
  directions. It does not convert a semantic getRGB array.
- Graphics.cpp maps legacy bitmap configurations to native N32/RGB565/alpha8.
  Skia's non-Windows default N32 shifts select RGBA; the supported Android
  arm64/x86_64 little-endian layouts give RGBA bytes and little-endian RGB565.
- Bitmap set/get pixel operations use SkBitmap write/readPixels, reaching
  SkConvertPixels and its raster pipeline. SkRasterPipeline_opts.h defines
  low-precision CPU RGB565 rounded packing and bit-replicated unpacking.
  The legacy SkColorData truncation helper is not used as the packing oracle.
  High-precision floating-point/GPU pipelines are outside this integer scope.
- Native reconfigure checks width × height × bytes-per-pixel against actual
  allocation capacity. Reconfiguration does not allocate replacement pixels.

The adapter deliberately fixes those Android little-endian layouts independently
of the desktop host and ByteBuffer typed order. `copyPixelsToBuffer` and
`copyPixelsFromBuffer` copy the actual owned byte array, with no getRGB alias,
premultiplication, swizzle or typed-byte-order conversion. Heap, direct, sliced
and read-only source ByteBuffers use their current position/limit; successful
copies advance position. A short buffer fails before copying. Read-only output
fails without a partial write. IntBuffer/ShortBuffer and raw access to borrowed
RGB/indexed/premultiplied/subimage layouts are explicitly unsupported. Incoming
copies require a live mutable bitmap. Retained borrowed backing identity and
pixel behavior remain covered by the existing marshal tests.

Opaque RGBA views still write a physical alpha byte of 255. Custom RGB565 and
alpha-only raster views convert real Java2D pixels over the same allocation;
there is no separate short/int pixel allocation hidden behind the byte count.
The codec backend normalizes semantic pixels to a temporary standard encoding
image so PNG writers cannot reinterpret RGB565 values as normalized samples or
alpha bytes as grayscale. Raw Buffer operations do not use that conversion.

## Source-backed local acceptance

Run with JDK 17, a C++17 compiler, and the official, hash-pinned Skia pipeline/header inputs:

```bash
python takx/compat/test-bitmap-native.py \
  --pipeline /path/to/SkRasterPipeline_opts.h \
  --color-priv /path/to/SkColorPriv.h
```

The runner performs no downloads. It verifies source hashes, extracts the
unchanged low-precision integer packing/unpacking functions and channel macros
into a temporary scalar-lane C++ math oracle, and compares Java pixel/storage results against its output. Skia's
BSD license is retained in LICENSE-Skia-BSD.txt. This oracle executes selected
integer math, not the Skia library, JNI, an Android runtime or a renderer.

Its 75,847 assertions include all 65,536 RGB565 words, 5,000 deterministic
packing vectors against the called CPU pipeline formulas (LCG seed 0x5a17e), all alpha-byte values, raw byte goldens,
ByteBuffer state/error cases, actual cross-config capacity, Java2D drawing,
codec pixels and fixed-shape region reuse. These are assertion counts, not API
counts or compatibility percentages. The original 239 bitmap contracts still
pass; only their private backing-array instrumentation changed from int[] to
the actual canonical byte[].

The actual pinned tile readers explicitly set premultiplication false, write
0xF1F2F3F4, and inspect a BIG_ENDIAN ByteBuffer for 0xF2F3F4F1 to detect RGBA.
That operation is tested unchanged in shape against the real byte storage.
Neither complete tile-reader class nor native GL code is claimed to run here.
Preferred decoder format selection belongs to the BitmapFactory/region decoder
slice; the new package helpers accept semantic pixels plus an explicit resolved
configuration without silently reshaping a fixed region destination.
