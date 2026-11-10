# Bitmap metadata, scaling and codecs

This slice adds real desktop metadata, scaling and PNG/JPEG encoding. Additional real owned formats and raw byte copying are documented in
[NATIVE-PIXELS.md](NATIVE-PIXELS.md). WebP and further configurations remain absent.

## Metadata and owned storage

Owned images report their actual implemented configuration. Borrowed Java2D rasters report null
because the adapter does not classify their arbitrary layout as an Android
configuration. `hasAlpha()` reports alpha capability/opacity metadata, not a
scan for transparent pixels. New ARGB images have alpha; opaque decoded images
retain opaque metadata. Metadata queries on recycled images explicitly fail.
Android documents those recycled queries as undefined behavior.

Opaque owned images use an RGB view over the same four-byte-per-pixel byte-array
allocation. Reads and writes then treat pixels as opaque. Decoding a new image
into an owned pool candidate updates its alpha model and shape while retaining
that exact allocation and its original capacity. Old borrowed views retain
their previous interpretation; as with reconfiguration, callers must stop
using those views before changing the image. Borrowed RGB/indexed/premultiplied
rasters retain their original image identity and actual alpha model.

## Scaling and encoding

`createScaledBitmap` creates real owned, mutable storage, preserves alpha
metadata, and uses Java2D nearest-neighbor or bilinear interpolation according
to the filter flag. It does not replace the source allocation. Following the
AOSP source path, an immutable source requested at its existing dimensions is
returned unchanged; a mutable source at the same size is copied. Nonpositive
or unrepresentable dimensions and recycled sources are rejected. Density,
color-space propagation, gainmaps and Android/Skia edge-pixel equivalence are
outside this desktop slice.

`compress` uses installed JDK ImageIO PNG/JPEG writers with a local memory
output cache; it does not change global cache settings or close the caller's
stream. PNG preserves lossless pixel/alpha data and ignores the quality hint.
JPEG receives quality 0..100 through the writer's explicit compression setting,
discards alpha, and encodes the straight RGB values rather than drawing them
over a background. JPEG output is opaque and lossy. Codec bitstream and color
conversion equivalence with Android native encoders is not claimed. Real output
I/O failures return false; invalid arguments and recycled images fail before
encoding. Fatal JVM resource errors are not converted to success.

Pinned behavioral reference: AOSP Android 14
[Bitmap.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Bitmap.java),
including createScaledBitmap/createBitmap identity/mutability, compression
quality/ownership contracts, configuration and alpha metadata. Native Skia is
not an executable oracle here. Tests use known real pixels, exact PNG round
trips, an independent JDK JPEG reader, JPEG quality/output comparisons, scaling
properties and existing actual upstream marshal/pool classes.

## Consumers and acceptance boundary

Pinned official ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e` uses
configuration/alpha in GLTextureAtlas, GLPendingTexture, GLTexture and GLTile;
scaling in GdalTileReader, StreamingTileClient, MobacTileClient2,
MaterialManager and AbstractTilePyramidTileReader; and PNG/JPEG compression in
GeoPackage, GeoPackageTileContainer, MBTilesContainer, OSMDroidTileContainer
and CustomMultiLayerMobacMapSource.

The same source also genuinely requests RGB_565: GLQuadTileNode2 decode options,
GLRenderGlobals texture/pixel creation, GLPendingTexture's opaque fallback and
GLTexture format/type selection. Those formats now have real owned storage. ALPHA_8 is
not requested in the scanned engine tree. The raw-copy contract and supported unpremultiplied layout are described in
NATIVE-PIXELS.md; `getRGB()` arrays are not used as a raw-memory substitute.

The bitmap harness now passes 198 checks, including its earlier 152 contracts,
opaque/alpha reuse transitions with allocation identity, borrowed metadata and
codec ownership, filtered scaling, PNG transparency, JPEG quality, failures
and independent decoding. Full engine, JNI/rendering and TAKX 5.7/5.8 acceptance
remain separate gates. No engine source is omitted or replaced by test facades.
