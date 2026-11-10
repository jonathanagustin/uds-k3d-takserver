# PNG/JPEG regions and decode sampling

`BitmapRegionDecoder` requests actual cropped image data through JDK ImageIO.
It supports file paths, the caller's current InputStream position, byte-array
ranges, repeated regions, subsampling, fixed-shape bitmap reuse and recycling.
Construction copies encoded bytes; callers retain their streams and may close
or change the original source after construction. Image readers and private
cache streams are released on recycle. Recycled decoders reject dimensions and
decode operations. The object serializes reads and recycling.

PNG and JPEG are supported. WebP/HEIF, file-descriptor constructors, Android
asset handles and hardware/wide-color/Gainmap decoding are not implemented.
Unsupported region formats throw `IOException`; ImageIO pixel-decoding I/O
failures return null with output dimensions reset. This is an ImageIO backend, not an
Android SDK artifact or Skia JNI replacement.

## Source contract

The Java wrapper, JNI and actual Skia implementation are pinned in
[region-source.lock.json](region-source.lock.json). AOSP is Android 14 commit
`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`; Skia's corresponding immutable
revision is `1145116447a46710a65e3a5deabb7d7c752af5ea`. The adapter is independently
implemented. The tiny unchanged Skia sampling helpers compiled by the test
retain their original notice and [BSD license](LICENSE-Skia-BSD.txt).

The actual native code matters here; generic Options documentation alone can
misdescribe region decoding:

- Fully outside rectangles throw. A partially outside rectangle retains padded
  output space, using zeros for the missing part, and places the real cropped
  pixels at the sampled left/top offset. Other empty/inverted regions return null.
- Region JNI does not read `inJustDecodeBounds`, `inMutable` or density fields.
  A fresh region is immutable even when those booleans are set. `inScaled`
  therefore does not enable/disable region subsampling.
- Both current native decoders clamp nonpositive sample sizes to one and pass
  positive arbitrary values through. The older power-of-two Java documentation
  is not enforced by this Android 14 implementation.
- PNG and proper-subset JPEG dimensions use integer division with a minimum of
  one. Whole-image JPEG first uses supported native factors 8/4/2 when divisible,
  rounds that native dimension up, then applies any residual integer sampling.
  Partial-outside padding is divided separately, as in Skia's region code.
- `inBitmap` returns the supplied object, preserves its dimensions/configuration
  and allocation, and clips larger decoded content into it. Output Options
  dimensions describe the decoded region even if that target is smaller.
  This differs from BitmapFactory's allocation-based reshaping. Regions whose
  dimensions or byte count cannot fit the adapter's integer allocation API are
  rejected before allocation.

The desktop region-reuse scope requires mutable owned storage. Native Android
can also write an immutable target with a warning; this adapter rejects it.
Borrowed/custom Java2D rasters are rejected for region reuse, while ordinary
owned ARGB/RGB565/ALPHA8 targets use their actual storage conversion. The
[region storage helper](REGION-STORAGE.md) documents the visible-color policy
when alpha metadata changes; no equivalence of unused native bytes is implied.

## BitmapFactory options

`BitmapFactory.Options.inSampleSize` now changes actual output pixels and
sampled bounds. `inScaled` defaults true, but there are no density inputs in
this adapter; as with Android when densities are unspecified, it adds no
density scaling. It is independent from subsampling.

The supported preferred configurations follow SkAndroidCodec selection:
RGB565 is chosen for opaque input; transparent encoded input falls back to
ARGB. ALPHA8 is available for decoded 8-bit grayscale, preserving raw gray
samples as alpha instead of accidentally applying Java's gray-to-sRGB gamma
conversion. Other color/depth inputs fall back to ARGB. Fixed region reuse
preserves the supplied target's configuration. Packing and pixel-buffer layout
follow the separately documented [owned storage contract](NATIVE-PIXELS.md).

Sampling is real center-cell pixel selection after ImageIO decoding. PNG
fixture pixels and scalar rounding are tested exactly. For whole JPEG images
with native-scale rounding, proportional centers span the full source image
rather than dropping its right/bottom edge after a ceiling dimension. JPEG
colors come from ImageIO, and Java sampling does not reproduce native DCT
resampling; bit-identical Android/Skia JPEG output,
color-profile equivalence and native memory savings are not established.
ImageIO may allocate full-image or region scratch before sampling; this is not
an allocation-free or performance-tuned decoder.

## Local acceptance

```sh
python3 takx/compat/test-region.py --source-dir /path/to/locked/reference/files
```

The external directory must contain files under the names in the lock. The
runner makes no downloads. It checks their hashes, compiles only the unchanged
Skia scalar dimension/start-coordinate helpers with C++11, and executes real
Java/ImageIO PNG/JPEG crop/sampling/reuse/lifecycle/ownership cases. A JDK with
`--release 11` and a C++ compiler are required. No Skia decoder or engine/native
renderer is executed by the scalar oracle.

Actual public Kernel consumers at ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e` are `AndroidTileReader` and
`GLBaseMap.ResourceTileReader`: they create region decoders from filesystem or
resource streams, request rectangular crops and sample sizes, then recycle.
Those full classes still require other tile-reader, OpenGL/native, IO and
resource infrastructure. This unit harness does not substitute fake versions
to claim that the complete consumers or either TAKX client work.
