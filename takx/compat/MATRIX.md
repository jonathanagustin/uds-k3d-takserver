# Finite affine Android graphics Matrix slice

This original GPL-3.0-only implementation supplies a bounded
`android.graphics.Matrix` subset for the public Kernel's actual bitmap flip
consumer. It is distinct from the native engine's `com.atakmap.math.Matrix`.
It does real finite 2D affine math and exposes a package-private Java2D bridge;
it is not a no-op Matrix or full Android/Skia implementation.

## Source-backed conventions

Official Android14
[Matrix.java](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Matrix.java)
at `299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368` defines these row-major slots:

```text
scaleX skewX translateX
skewY  scaleY translateY
0      0      1
```

Points are column vectors. Android pre-concat is `M' = M * other`;
post-concat is `M' = other * M`. Consequently, pre-translation through a scale
scales the translation, while post-translation does not. Scale about a pivot
uses translation `(px - sx*px, py - sy*py)`. The source SHA256 is
`8a2ca2968326437cf8df4d2dc17b11a8bc398c33943f0aa3f40dd5a12db6da50`.

The official Android14
[CTS MatrixTest](https://android.googlesource.com/platform/cts/+/refs/tags/android-14.0.0_r1/tests/tests/graphics/src/android/graphics/cts/MatrixTest.java),
SHA256 `9387c31a104e1f4c3c7ad43d1d5196f025080c14514096eda8918d1b6d39073f`,
provides numeric vectors for `setScale(1,2)` and
`setScale(1,2,3,4)` (the latter has Y translation -4). Those facts are tested
locally alongside independent Java2D affine math. The official
[SkMatrix.cpp](https://android.googlesource.com/platform/external/skia/+/refs/tags/android-14.0.0_r1/src/core/SkMatrix.cpp),
SHA256 `179e258fd7065c29beb1ab7e318b95ce437cc34edc35379d518e553347694df2`,
was also inspected for affine/rectangle mapping boundaries. No Android-native test runtime
or Skia library was executed; the original AOSP Matrix delegates its arithmetic
to native Skia, so this is not a bit-for-bit native floating-point oracle claim.

## Supported operations and explicit boundaries

Supported: identity/reset/copy/set, scale (including pivot), translation,
pre/post scale/translation/concatenation, general finite affine values,
point mapping with overlap-safe arrays, rectangle bounds, rectangle-preserving
classification, inversion and an independent `AffineTransform` bridge.
Singular or non-finite inverse results return false without changing the target.
The bridge uses Java2D's coefficient order explicitly rather than transposing
Android translation/skew slots. Mutating a returned bridge cannot change Matrix.

Perspective or non-finite matrix values throw `UnsupportedOperationException`
before changing the matrix. `isAffine()` reflects this enforced invariant.
Projective mapping, native precision equivalence, vector/radius APIs, rotation
convenience methods, setRectToRect, poly-to-poly and the other Android surfaces
are not implemented. Float storage with double intermediate concatenation and
inversion is checked with numeric tolerances, not advertised as exact Skia
rounding. This subset must not silently grow into an assumed general SDK.

## Actual consumer, pixels and integration limits

At official ATAK source revision
[`9f6893dd657feacc35ec5de03dad721c2e44170e`](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/engine/src/main/java/com/atakmap/android/maps/graphics/GLImageCache.java),
`GLImageCache` is the engine's only `android.graphics.Matrix` importer. Its static
flip matrix is created/reset and scaled `(1,-1)`, then passed into the
`Bitmap.createBitmap(source,x,y,width,height,matrix,filter)` overload.

The local tests render real ARGB Java2D pixels through that flip transform with
the required bounds-origin translation, and verify vertical reversal and
nearest-neighbor 2x scaling. They also cover 200 independently generated affine
maps/inverses, aliases, overlapping point arrays, invalid input and unchanged
state after rejected perspective input. Observed result: 2,861 assertions.

This commit does not modify Bitmap or implement that missing crop/transform
overload. The real GLImageCache path also involves OpenGL/native engine state;
neither full consumer compilation/runtime nor native rendering acceptance is
claimed. The matrix/bridge is a reviewable prerequisite for the separately
coordinated Bitmap integration. Both official TAKX profiles remain candidates.

Run offline with a JDK supporting release11 and Java2D:

```sh
python3 takx/compat/test-matrix.py
```

The test compiles only real Matrix/RectF and its behavioral tests into temporary
storage. It has bounded compiler/runtime deadlines, needs no display, and does
not build native GIS or trigger a workflow.
