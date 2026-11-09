# Desktop coordinate and rectangle primitives

This bounded slice of `uds-desktop-android-compat` 0.1.0 provides real mutable
`android.graphics.Point`, `PointF` and `RectF` values. Coordinates are stored and
operations actually compute their results. It does not implement Android
Parcel/Parcelable, integer Rect/Insets overloads, native graphics or Matrix.
Color and the complete Android geometry API remain outside this slice.

## Authoritative source and adaptation

The reviewed official source revision is
[TAK-Product-Center/atak-civ 9f6893dd657feacc35ec5de03dad721c2e44170e](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).
Its separately packaged public `gov.tak.platform.graphics` classes already supply
useful behavior, but do not satisfy engine imports of `android.graphics`.

- Point and PointF are original GPL-3.0-only implementations, informed by the
  simple coordinate contract in `takkernel/port/src/jre/java/gov/tak/platform/graphics/Point.java`
  and `PointF.java`. Copy/set/offset/negation/equality and floating-point length
  are computed locally, without a binary SDK or native dependency.
- RectF adapts `takkernel/port/src/main/java/gov/tak/platform/graphics/RectF.java`,
  original SHA256 `66ff23f30855d2b0526a6e85020348c38c429502265045384d9022f68d8593ed`.
  Its AOSP copyright and Apache-2.0 notice remain in the source; the
  [complete license](LICENSE-Apache-2.0.txt) accompanies it. That source identifies
  AOSP revision `1a522bd5e7947ee5a4b44951b9099861c1dbcce4` as its ancestry.
  The adaptation changes the package and Rect-typed operations to RectF-typed
  operations, removes annotation dependencies and the unsupported Insets
  overload, corrects copied integer-center documentation and the type label,
  and makes signed-zero hashing consistent with the retained numeric equality.
  No unofficial implementation or prebuilt artifact was used.

Rectangles retain caller coordinates, including inverted rectangles. Point
containment includes left/top and excludes right/bottom; intersection requires
positive overlap and leaves the receiver unchanged on failure. Sorting is
explicit. RectF numeric equality treats signed zeros as equal, with equal hashes.
These are geometry values, not implicit coordinate-system conversions.

## Point equality and length reference

The additional Point/PointF methods follow official AOSP
[Point](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Point.java) and
[PointF](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/PointF.java)
at Android 14 tag `android-14.0.0_r1`, commit
`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`. Reviewed source SHA256 values are
`df644b622a632a981299c5979cd23be85bf0b740c756ae1f3383782db92cab3c` and
`2a3c5c9c032d81c405d36bc6821dcfdeb0b68ab9e7554ff772387f5fde9797ec`, respectively.
These are behavioral references for original implementations, not copied Android
Parcelable classes or a claim to implement the entire Android 14 SDK.

Object equality accepts identity and requires the same runtime class. PointF
object equality uses Float.compare: NaN coordinates compare equal, while signed
zeros differ. Its coordinate `equals(float,float)` overload instead uses numeric
`==`, so NaN coordinates differ and signed zeros compare equal. PointF hashing
normalizes zeros as that reference does; unequal values may share a hash.
Length uses Math.hypot, as the official reference does (also verified in Android
8.1, 10 and 12), preserving very large and subnormal magnitudes instead of
introducing float multiplication overflow/underflow. Infinity/NaN handling is
tested explicitly. Earlier Android releases are not asserted to have identical
behavior.

## Real consumer acceptance

Run offline with trusted JDK 17 on PATH:

```bash
python3 takx/compat/test-geometry.py --source /path/to/clean/pinned/atak-civ
```

The runner verifies the source revision and consumed tracked files, exports
unchanged source bytes into a temporary directory, and compiles with Java 11
compatibility. Its behavioral checks execute actual public Kernel consumers:

- `com.atakmap.math.PointD` construction and int/float conversion, including
  negative fractional truncation and independent copies.
- `TileMatrix.Util.getTileIndex` and `getTilePoint`, including negative indices
  and the upstream truncation behavior for negative fractional indices.
- `Vector2D.clipPolylineCohenSutherland` for crossing, inside and outside lines,
  checking returned coordinates and restoration of the input buffer position.
  This consumer uses a lower-left origin and an inverted RectF top/bottom;
  the adapter preserves those supplied fields rather than normalizing them.

Additional direct checks cover mutable/copy behavior, negative and fractional
coordinates, offsets/insets, boundary exclusion, empty/inverted rectangles,
intersection failure, union, sorting and signed-zero equality/hash consistency.
The full public port compile remains a separate check. These tests neither run
the full engine nor establish map rendering, native GIS/JNI or TAKX compatibility.
