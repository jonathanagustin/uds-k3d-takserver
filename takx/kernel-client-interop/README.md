# Public Kernel client interop source profile

This project profile extends the actual public Kernel 8.30.5 source. It does not identify that source as the private Kernel versions requested by TAKX 5.7 or 5.8. The source revision, nine original file preimages/postimages, owned viewport policy, and exact public renderer dependencies are locked in `inputs.lock.json`. Original source projections and qualified SDK/native proofs remain read-only.

The patch adds an asset-manager Roles icon overload returning the genuine public gov Bitmap through its public pixel-array constructor. It copies pixels from the existing Android composition and retains the Context-based Android icon cache. The existing public Bitmap initializer registers the real gov Bitmap to BufferedImage/Android marshals used by the Client; no Android-to-gov converter is fabricated. It forwards nullable renderer font names through the real C/D/E providers; null retains `serif`, and the existing renderer locks remain in use. Java label hints use the existing native default bits and marshal into the real Core options. Scene ID visibility and query methods delegate to the existing Core SceneLayer APIs. Distinct JNI names preserve the URI setter ABI. A query cursor retains its native unique owner until Pointer allocation succeeds, then uses the existing FeatureCursor interop and explicit cursor-close ownership.

`public-viewport-fit-v1` is an explicit project policy. It uses the shortest cyclic longitude envelope, WGS84 meridian geodesic height (numerical integration), and a midpoint WGS84 parallel-width approximation. Resolution is the larger per-axis metres-per-pixel ratio. Positive dimensions apply independently; each zero dimension uses 256 pixels. Negative dimensions, null points, nonfinite coordinates, and latitudes outside ±90° are rejected. Empty, single, and geographically coincident extents use 1 metre per pixel. Existing caller minimum-resolution and bounding-box branches remain unchanged. This is not a recovered private SDK algorithm.

The default phase verifies inputs without invoking a compiler or JVM. Explicit phases compile the eight actual Java sources (`java`), run real headless controls (`controls`), or check the two patched JNI translation units against an existing genuine native compilation graph (`syntax`). The latter uses `-fsyntax-only`; it does not produce native objects or link libraries. All phases require a new output directory. Commands use owned process groups, finite deadlines, a 35 MiB output bound, and a 2 GiB free-space floor. There is no download/install phase.

For example, using separately acquired and checksum-verified JSVG 1.6.1 and geodesy 1.1.3 from the locked mil-sym-java 2.1.5 runtime dependency declaration:

```sh
python3 -B takx/kernel-client-interop/build.py --phase controls \
  --source /path/to/cached-official-git \
  --sdk-proof /path/to/qualified-sdk-package-proof \
  --public-jars /path/to/exact-locked-renderer-jars \
  --java-home /path/to/qualified-jdk-17 \
  --output /path/to/new-controls-output
```

For JNI syntax checks, select `--phase syntax --native-proof /path/to/fresh-kernel-native-proof`. Use the JDK and current-host native inputs bound by those genuine producer receipts. The overlay is a project source profile, not a replacement SDK release or a complete TAKX build prerequisite.

Headless controls exercise actual bitmap composition and independent pixel placement, cached/fresh icon behavior, C/D/E font output and default forwarding, concurrent font switching under the existing locks, and viewport size/aspect/IDL/global-span/pole/error cases against WGS84 reference distances. They reject SDK native libraries in process maps. They do not execute the new label/Scene JNI bridges. Real multipoint output/detail comparisons, native feature execution, rendering, client launch, and private-version equivalence remain unqualified. A compile pass alone does not qualify those behaviors.

Run offline guards with `python3 -B -m unittest discover -s takx/kernel-client-interop -p test_build.py`. These do not compile third-party code or run native APIs. Failed attempts stay separate from accepted outputs; receipts bind the actual consumed producer, sources, classes, headers, tools, and dependency bytes.
