# Public elevation JNI constructor correction

Official Kernel 8.30.5 at `9f6893dd657feacc35ec5de03dad721c2e44170e`
looks up `ElevationSource.QueryParameters`' constructor using `ElevationSource`'s
class. It then passes that method ID to `NewObject` with the QueryParameters
class. These classes are unrelated. A real attached public elevation source
reaches this path during `ElevationManager.getElevation` bulk sampling and aborts
under `-Xcheck:jni` with `Wrong object class or methodID passed to JNI call`.

The one-line patch obtains the constructor from its declaring QueryParameters
class. Both source images and the exact patch are locked. `prepare.py` defaults
to local verification without starting any process. Its explicit prepare phase
reads one exact cached official source, performs only the reviewed substitution,
verifies the complete postimage, and writes a fresh disjoint output. It neither
builds nor loads a library, and changes no cached official source.

```sh
python3 -B takx/kernel-elevation-jni/prepare.py
python3 -B -m unittest discover -s takx/kernel-elevation-jni -p 'test_*.py' -v
python3 -B takx/kernel-elevation-jni/prepare.py --phase prepare \
  --source /path/to/cached/official/source --output /path/to/new/source-output
```

`tests/ElevationJNIControls.java` uses the actual public elevation registry,
source builder, chunk sampler and native bulk sampling. Its owned analytic plane
checks attachment, all 81 sampled elevations, detach and the absence of values
after detach. Its no-resource sampler has nothing to release in `dispose`.
The first argument is an independently reviewed native load-order manifest of
`SHA256 absolute-library-path` lines, as produced by the full native experiment;
the fixture is not a loader/authentication front door. Default CI never runs it.

The original complete native composition aborts and emits two JNI warnings.
Failure receipt:
`1d90b0ae9ac1b83354ffe1cd36f5a0ea256af8cb8a32de1634a22aab892f3cbe`.
An isolated one-source recompile/relink corrects the abort and passes all 166
functional checks, including actual Java sampler callbacks. It still emits seven
unchecked-exception JNI warnings, so strict validation fails. Failure receipt:
`97c5c34d8508cdec446330a03078065f2ae163daa75ea9570d2e4cefe584cb6f`.
Original sources/objects and both failures are retained. This causal relink is
not a fresh complete native variant and is not adopted as a qualified artifact.

Four offline guards and exact real source preparation pass. Remaining work
includes callback/cleanup exception boundaries, primary error preservation,
authenticated full-graph native integration and strict actual-library controls.
The independent contour grid algorithm does not resolve those native failures.
No strict elevation, full SDK or client acceptance follows from this source fix.
Refs #374 and #486.
