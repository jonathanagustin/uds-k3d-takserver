# Bitmap subset and affine transform

`Bitmap.createBitmap(source, x, y, width, height, matrix, filter)` copies a
validated source subset into real owned ARGB pixel storage, optionally applying
the finite affine Matrix slice. This is the overload used by the pinned
GLImageCache to flip an image vertically before recycling the original.

The operation maps the subset's local `(0,0,width,height)` bounds through the
Matrix, rounds the resulting width/height, and translates the mapped origin
back to the output origin. A translation therefore does not add empty padding.
Negative scales and quarter-turns retain the expected pixel orientation.
The source subset is a bounded Java2D image view; drawing it does not detach,
reshape or replace the source allocation. Filtering selects nearest-neighbor
or bilinear interpolation. Non-rectilinear transforms enable the backend's
antialias hint; Java2D edge coverage is not asserted to match native Skia.

Full-source identity operations return the original only when it is immutable.
Mutable full-source identity operations and immutable partial/nonidentity
operations produce independent, mutable images. Borrowed RGB/indexed/
premultiplied source layouts keep their original backing identity; results own
ARGB storage with the source's alpha metadata. In the pinned AOSP implementation,
createBitmap restores `source.hasAlpha()` after choosing the transformed
allocation, including a non-rectilinear transform. This final alpha flag is
preserved here. Opaque results therefore retain opaque interpretation at any
unpainted corners; transparency is not invented for them.

Reference: AOSP Android 14
[Bitmap.createBitmap](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Bitmap.java#L888),
especially subset validation, immutable identity reuse, mapped-bounds rounding,
source alpha restoration and baseline canvas translation. No native renderer
is copied or executed. Perspective and non-finite matrices remain rejected by
Matrix; non-finite/empty/unrepresentable mapped bounds fail before allocation.
Invalid ranges use long arithmetic to reject overflow. Invalid input does not
modify the source. Recycled sources are rejected.

The bitmap harness now has 239 checks. New coverage includes the exact
GLImageCache flip/copy/recycle operation shape, crop pixel independence,
flip-twice recovery, quarter-turn orientation, translation without padding,
filtering, shear coverage, alpha metadata, mutable/immutable instance rules,
borrowed storage identity and invalid/lifecycle failures. It runs the unchanged
real upstream marshal chain and ResourcePool, not a substitute GLImageCache.
The full GLImageCache still requires native GL/engine dependencies; no full
engine, renderer or TAKX client acceptance is claimed.
