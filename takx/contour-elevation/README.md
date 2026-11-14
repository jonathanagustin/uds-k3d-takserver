# Contours from the public elevation registry

This project adapter connects `ContourGrid` to the actual public Kernel
`ElevationManager` and source registry. It samples a bounded north-to-south grid
one row at a time, applies an exact source-type filter and caller flags, then
runs the existing triangulated contour algorithm. It introduces no
`gov.tak.api.contour` placeholders or private SDK version aliases.

The result reports finite/total sample counts. Missing elevations remain NaN;
cells touching them produce no contours. An unavailable or detached provider
returns zero coverage and no lines. Cancellation and provider/progress callback
errors return no partial result. The adapter neither attaches nor disposes
caller-owned sources. Cancellation is checked between native batches; it cannot
interrupt a callback already executing inside a native query. The test runner
separately enforces a hard process deadline.

The actual full Native07 composition passes 275 controls with zero strict JNI
diagnostics. These check analytic-plane contour vertices, bounded coordinates,
immutable output, monotonic progress, source-type isolation, missing data,
cancellation, provider exception identity, recovery and detach behavior. The
published runner's receipt is
`eb63e5aefbae89c0546944c86d9f236e13ce141f589489bd6a2079022acdf74b`.
The initial separate experiment is retained with receipt
`a58bad1751c332e90422f101354b04953ea39aa59fa1e33113297b3c5809460a`.

## Source-only verification and opt-in controls

`python3 -B takx/contour-elevation/build.py` verifies the owned sources and contour
algorithm without importing an executor or launching a process. Four offline
guards cover source/acceptance drift, explicit opt-in, dependency refusal and
output safety. Native controls require the source-locked elevation consumer
profile staged in PR #591 and its exact frozen native/Java producers:

```sh
python3 -B takx/contour-elevation/build.py --phase controls \
  --native /path/to/context-fresh-native-07 \
  --java /path/to/client-java-native07-01 \
  --jdk /path/to/reviewed-jdk \
  --elevation-profile /path/to/kernel-elevation-jni \
  --output /path/to/new-control-output
```

The lock authenticates the external consumer recipe before importing it. That
consumer verifies the exact frozen producer receipts, staged native/Java
sources, closed classes/headers, classpath archives, native manifest, mapped
ELFs, compiler/JDK/JNI headers and source controls. This adapter runner adds its
own source and algorithm pins, fresh closed class output, disjoint input/output
roots, 40-second command deadlines, 2 MiB logs and 8 MiB output quotas. Inputs and
compiled products are rechecked between commands. Failures retain logs and a
typed receipt. It requires the frozen layout's absolute dependency/JDK paths and
the qualified local compiler environment, rather than a portable native build.

This is project-level provider integration. Complete TAKX 5.8 contour API,
rendered layer integration,
client compilation/runtime, private-SDK equivalence and complete renderer/SDK
acceptance remain open. The existing pure-grid profile's provider flag remains
false because that profile alone loads no provider. All broad acceptance flags
in this adjacent adapter profile also remain false.

## Native contour features and styles

`ContourFeatures.create` converts contour polylines into the actual public
Kernel `LineString`, `BasicStrokeStyle`, `AttributeSet` and `Feature` objects.
Every Nth configured level, relative to the supplied base, is major; negative
indices follow the same rule. Non-aligned levels, invalid coordinates and
unbounded stroke/vertex configurations refuse before native allocation. Geometry
is two-dimensional and features clamp to the surface. Labels and attributes
explicitly identify elevations as metres HAE, matching ElevationManager output,
rather than promising mean-sea-level heights.

The batch owns its native features. Borrowed feature references must not be
disposed by callers or used after the batch closes. Use try-with-resources for
the batch. Temporary geometry/style/attribute objects are disposed after native
feature construction; the controls verify that the features retain their actual
geometry, stroke colors/widths and elevation/class/index metadata. Cancellation
or callback failure after partial conversion disposes completed features and
returns no partial batch. Closing is idempotent and prevents further batch access.

The expanded published runner passes 539 assertions with zero strict JNI
diagnostics. In addition to provider controls, it checks native geometry/style
readback, immutable feature membership, negative/major/minor levels, borrowed
lifetime, partial-allocation cancellation, callback exception identity, cleanup
and recovery. Receipt:
`9a77f536567ec4fc1fcec31f1b62c49ad9b72149cb6e14750133bd9bb9181baf`.
The preceding 275-check provider-only and intermediate native-feature receipts
remain retained. No native producer source changed. This covers native feature
construction, at that stage not a feature datastore, rendered map layer, GL drawing, label
placement, client contour API or complete client runtime. Those gates stay open.

## Owned persistent feature layer

`ContourLayer.create(name, databasePath, batch)` now copies borrowed native
features into a real `FeatureSetDatabase2` and exposes its `FeatureLayer3`. It
requires a new database file, refuses symlink ancestors, and creates the file
with POSIX owner-only permissions. Existing files are never overwritten. The
input feature batch stays caller-owned. The wrapper owns and disposes the datastore; callers must not dispose borrowed
layer/store references. Detach any borrowed layer from its map before closing
the owner. Borrowed references are then out of scope.
Closing is idempotent and leaves the database file for explicit caller retention.
On construction failure, the owned store is disposed and the new file remains
available for diagnosis. The wrapper is for single-thread use on the qualified
POSIX host; cross-platform filesystem behavior remains unqualified.

The preceding full-library replay completes 569 assertions with zero strict JNI
diagnostics. It verifies layer/store queries, native feature-set identity and
metadata, visibility, existing-file and symlink refusal, caller-batch ownership,
closed-owner access refusal and persistent readback after closing/reopening the
synthetic datastore. The test removes only its own feature set after readback
and fingerprints the retained synthetic database. Receipt:
`b730cd39a0ae72648d0a3b1b21dd8261bcd99bb5b477d6b6d215598b69e2b1ce`.
The initial standalone datastore/layer probe passes 15 checks with receipt
`7336cdf20a0716ed779061b8968a89460858fb6f80bd87385747913b1a526ab1`;
intermediate feature/layer experiments remain retained separately. No native
producer source, SQLite provider or private fixture was replaced. This proves
the scoped datastore/layer CPU path, not rendered pixels, GL drawing, label
placement, clipping or complete TAKX contour/client runtime acceptance.

## Clipping through the native layer path

`ElevationContours.Result.clipped` applies the source-locked `ContourClip`
component before feature/layer construction. Sample counts continue to describe
the original sampled grid; clipping geometry does not recompute coverage for
the smaller extent. The latest native replay verifies clipped analytic vertices
and stores the clipped styled features in its one owned persistent datastore.
It passes 593 assertions with zero strict JNI diagnostics, authenticating 5,564
inputs and 13 compiled products. Receipt:
`87ef800e03bc0eadee0786327abf567477dc4ad0bd31417101a520b085fc05b6`.

An intermediate two-database experiment exceeded the unchanged 8 MiB aggregate
output limit. Its receipt, exact authenticated failed source, logs and both
synthetic databases remain retained; its functional marker alone is not accepted.
The subsequent experiment consolidated the test into one owned database, keeping
all existing quotas and ownership guards. Native producer code remains unchanged.
Rendered pixels, GL drawing, label placement, complete client API/runtime and
full renderer/cache qualification remain open.
