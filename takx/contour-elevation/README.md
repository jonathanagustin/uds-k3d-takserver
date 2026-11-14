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
geometry/layer/style integration, spatial clipping, major/minor classification,
client compilation/runtime, private-SDK equivalence and complete renderer/SDK
acceptance remain open. The existing pure-grid profile's provider flag remains
false because that profile alone loads no provider. All broad acceptance flags
in this adjacent adapter profile also remain false.
