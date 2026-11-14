# Bounded contour grid kernel

`ContourGrid` generates real contour polylines from caller-owned elevations in
meters on a regular WGS84 grid. This is a separate project implementation under
`gov.tak.project.contour`; it does not supply missing `gov.tak.api.contour` types
or qualify the complete TAKX 5.8 Platform/Client.

Every cell is split along its northwest/southeast diagonal and interpolated
linearly in each triangle. Shared grid edges establish connectivity without
rounding-based coordinate joins. Open paths and closed rings are stitched,
consecutive duplicate vertices are removed, and coincident level-aligned ridges
are deduplicated. Equal samples belong to the upper side of a contour level.
A cell containing a NaN sample is omitted in full; infinity is rejected. A flat
surface emits no isolines. These are explicit project policies, with no GDAL or
private SDK behavior-equivalence claim.

Input dimensions, contour levels, total cell/level work and emitted vertices are
bounded. Bounds must be finite, non-wrapping WGS84 coordinates. Generation copies
the input and returns deeply immutable records. Cancellation and progress
callbacks are synchronous; cancellation or a callback error returns no partial
result. Levels are ascending and progress is monotonic. Intervals below numeric
resolution and overflowing level indices refuse generation.

The 865 analytic controls cover planes, closed hill rings, no-data gaps,
triangulated saddles, flat fields, exact-level ridges, all 81 ternary 2x2 grids,
immutable output, cancellation, primary callback identity, work/numeric bounds
and overflow-resistant interpolation. This validates the mathematical grid
component. Elevation source selection/sampling, arbitrary spatial clipping,
major/minor classification, TAK geometry ownership, style callbacks, datastore
layers and complete client integration remain open in #374/#486.

Default verification and four offline source/launch guards start no process:

```sh
python3 -B takx/contour-grid/build.py
python3 -B -m unittest discover -s takx/contour-grid -p 'test_*.py' -v
```

Opt-in controls require the qualified Java 17 compiler/module hashes recorded by
the existing client compiler profile and a fresh output outside source/JDK roots:

```sh
python3 -B takx/contour-grid/build.py --phase controls \
  --java-home /path/to/qualified/jdk17 --output /path/to/new/control-output
```

The producer downloads and installs nothing, authenticates consumed bytes before
and after execution, uses a fresh classpath without annotation processing, and
runs `-Xcheck:jni` with a 256 MiB heap. Each child has a 30-second deadline and
bounded logs/disk use through the existing process-group runner. Failures retain
a failed receipt; success records complete class hashes and zero strict JNI
diagnostics. The pure Java controls load no project SDK classes. The four JDK
pins identify its compiler/modules, without claiming complete host equivalence.
All contour API/provider/layer/client acceptance flags remain false.
