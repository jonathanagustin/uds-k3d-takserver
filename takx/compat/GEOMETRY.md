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
explicit. Floating-point signed zeros compare equal and have equal hashes.
These are geometry values, not implicit coordinate-system conversions.

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
