# Packed colors and integer rectangles

This additional `uds-desktop-android-compat` 0.1.0 slice implements actual packed
integer ARGB operations and mutable integer rectangle geometry. It is not the
Android graphics runtime, an upstream SDK artifact or full TAKX compatibility.

## Source and license

The reviewed official source is
[TAK-Product-Center/atak-civ 9f6893dd657feacc35ec5de03dad721c2e44170e](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).

- Rect adapts `takkernel/port/src/main/java/gov/tak/platform/graphics/Rect.java`,
  SHA256 `dd7a0e3554b43e693753bc3657781863d9d738b2bc42701711d1e2665f82411c`.
  Its AOSP copyright, Apache-2.0 notice and the existing complete
  [license](LICENSE-Apache-2.0.txt) are retained. Changes are the package,
  removal of annotation imports and omission of the unsupported Insets
  overload. Integer coordinate arithmetic, including overflow, remains intact.
- Color is an original GPL-3.0-only implementation of packed values. Its channel
  extraction, names and parsing behavior are tested against the actual pinned
  `takkernel/port/src/main/java/gov/tak/platform/graphics/Color.java`, SHA256
  `1d65dfd1116a6da7ebaa7c9ac09bde13b451b0b834636a545cfd9a1f2fe49921`.
  Integer `rgb`/`argb` packing follows official
  [AOSP Color](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/graphics/java/android/graphics/Color.java)
  at Android 14 commit `299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`, source SHA256
  `f9c3b1cc137bc9e944e60c05f9ac5eea92dbae8f680b5896d12d764796ac89ea`.
  These APIs use raw shifts; out-of-range channels are not silently clamped.

Color supports integer constants, channel extraction, integer rgb/argb and
parseColor. Parsing retains official public-port behavior: six/eight-digit
hex forms, its 23 case-insensitive color names, locale-independent lookup and
actual failure categories for invalid/empty/null input. Long.parseLong also
accepts a leading sign in the hex substring when the total length matches;
this surprising oracle behavior is tested rather than silently tightened.
HSV conversion is deliberately absent: the pinned public port uses normalized
hue while Android's API uses degrees. No partially matching implementation or
native facade is supplied. Floating-point/wide-gamut Color and NaN handling
are therefore outside this integer-only slice.

Rect supports construction/copy, set/clear, equality/hash, dimensions/centers,
offset/inset, containment, intersection, union and explicit sorting. Right and
bottom point boundaries are exclusive. Unsuccessful intersection does not
change the receiver. Inverted coordinates and integer overflow are preserved;
centers retain the official integer arithmetic-shift behavior for negative and
overflowing sums. Parcel/Parcelable and Insets remain unsupported.

## Acceptance and engine boundary

```bash
python3 takx/compat/test-color-rect.py --source /path/to/clean/pinned/atak-civ
```

The offline runner verifies the revision and exports unchanged tracked official
Rect/Color/Insets and annotation sources into temporary storage. It compiles
those real source oracles and the adapters locally with trusted JDK 17,
`--release 11`, then runs deterministic differential checks. Cases include
random packed pixels/channels and rectangles, boundary exclusion, inverted and
empty rectangles, failed intersections, copy/mutation/equality, overflow,
negative centers, valid and malformed parse inputs, alpha zero and Turkish
locale lookup. No unofficial binary or native dependency is adopted.

Actual engine consumers include `TerrainRGB.decode` (channel extraction),
`DepthSampler` (depth-channel extraction), feature renderers (argb),
`KmzLayerInfoSpi` (parseColor), and `GLBaseMap`, `AndroidTileReader` and
`SQLiteSingleTileReader` (Rect regions). Their containing classes still require
missing Bitmap lifecycle/options, Canvas, GL/native or database behavior.
These tests therefore use actual source oracles and direct API behavior; they
do not pretend to execute those whole engine consumers with substitute types.
The full public port compile is separate. A successful primitive test does not
establish full engine compilation, native GIS/JNI or desktop interoperability.
