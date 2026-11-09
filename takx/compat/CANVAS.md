# Desktop software Canvas slice

This original GPL implementation draws real pixels through Java2D into the
current writable Bitmap storage. It is part of uds-desktop-android-compat,
not Android native Canvas, Skia, OpenGL or an accepted TAKX client.

The pinned official ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e`
uses Canvas for:

- Bitmap copying and source-rectangle scaling in GLTextureAtlas,
  GLPendingTexture, GLBaseMap, AndroidTileReader and tile-pyramid readers.
- Source Rect to destination RectF composition in MobileImageryTileReader
  and AbstractTilePyramidTileReader.
- Paint-alpha layer composition in CustomMultiLayerMobacMapSource.
- Debug rectangles/text in AbstractTilePyramidTileReader and substring glyph
  rendering in MapTextFormat.renderGlyph.

These consumers motivate the implemented overloads. No transform, save/restore,
clip-state, path, shader, filter, density, GPU, native-handle or other drawing
methods are added as placeholders. Source rectangles must be inside the source
bitmap; out-of-bounds rectangles and non-finite coordinates are explicitly
rejected. Null bitmap paint means default source-over composition. Rectangular
bitmap scaling uses nearest-neighbor sampling, independent of shape antialiasing.

## Storage and drawing behavior

The Canvas retains a Bitmap, rather than a long-lived Graphics2D or stale image.
Each operation validates the target and obtains its current image, creates a
Graphics2D, and disposes it afterward. Existing Canvas instances therefore see
owned bitmap reconfiguration. Recycled or immutable targets reject drawing;
recycled sources also reject bitmap drawing. The surface cannot reconfigure a
borrowed image: it draws directly into its unchanged actual Java2D color model.
RGB, indexed, premultiplied and subimage backing identity remains intact.

Bitmap drawing clips to the destination rectangle and bitmap bounds, scales the
requested source region, and composes source alpha with Paint alpha using
source-over. Paint RGB does not tint a bitmap. Empty rectangles draw nothing.
Shapes use Paint color/alpha, fill/stroke style and finite nonnegative stroke
width. Zero width is a one-device-pixel software hairline; joins use miter limit
four and butt caps. Fill-and-stroke fills a union once, avoiding doubled alpha
where the fill overlaps the stroke.

Text drawing uses the existing Typeface resolver, text size, antialias setting,
text advance and alignment contracts. Java2D TextLayout supplies shaped glyph
outlines at the requested baseline; Paint style fills/strokes the outline.
String ranges use start/end indices as consumed by MapTextFormat. Text pixels,
font fallback, hinting and antialias edges are desktop behavior; Android/Skia
pixel equivalence is not claimed. Invalid Paint alpha outside 0..255, stroke
widths and non-finite coordinates are outside the supported input range.

The behavioral references are AOSP Android 14
[Canvas](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Canvas.java)
and the existing Paint/Typeface references in FONT.md. These document mutable
bitmap targets, source/destination rectangles, alpha/style, baseline and text
alignment. Their native Android renderer is not executable in this JDK harness;
no native oracle or copied AOSP renderer is presented.

## Local acceptance

Run `./takx/compat/test-canvas.sh` with JDK 17; it compiles with `--release 11`
and runs headlessly. Its 43 checks verify translated/cropped/scaled pixel
colors, fractional destinations, device-bound clipping, alpha multiplication/source-over, rectangle
interiors/edges, fill-and-stroke alpha, glyph ink/outline coverage, text alignment/ranges,
reconfiguration, recycled sources/targets and immutable destinations.

The bitmap harness additionally compiles the unchanged official marshal chain
and ResourcePool. Its 198 checks include drawing into actual borrowed RGB,
indexed, premultiplied and subimage storage, plus the previous 148 bitmap/reuse
contracts. Neither harness substitutes dummy engine consumers. Complete tile
readers and MapTextFormat retain other engine/native dependencies and are not
claimed as compiled or runnable by these tests. Full engine, native rendering
and TAKX 5.7/5.8 acceptance remain separate gates.
