# Public Kernel format regressions

This harness adapts real upstream test slices and a bounded authored 3D fixture to the public-source desktop
SDK. It calls the production Kernel classes, native SQLite/GeoPackage code and
DTED source factory. It contains no replacement SDK classes or test codec.

The pinned source paths, Git blobs, hashes and adapted methods are in
`upstream.lock.json`. The tests derive from official ATAK source at
`9f6893dd657feacc35ec5de03dad721c2e44170e`, under its GPLv3 license. The SDK keeps
its separate dependency notices. No upstream test runner, Android fixture helper,
JUnit implementation or bundled test binary is copied.

The initial slice checks:

- DTED `.dt0` through `.dt3` discovery with both query order settings. These are
  intentionally empty files, as in the upstream test; this does **not** test
  decoding elevation samples or prove the returned sort order.
- MBTiles default-SPI creation, actual SQLite schema compatibility, seven tile
  byte inserts, updates, disposal and writable SPI reopen, plus a direct native
  SQLite read-only schema connection. Opaque tile bytes are the
  upstream database test pattern; this does not test image decoding or every
  MBTiles schema implementation.
- GeoPackage 256 × 256 float gridded coverage, persisted nondefault offset/scale,
  terrain metadata controls and all decoded elevation samples.

The actual default IO provider ignores the SPI read-only option by calling
`Databases.openOrCreateDatabase` unconditionally. The original upstream test
reopens writable; this harness follows that scope and does not claim SPI
read-only enforcement. The first runtime failure exposing the unsupported extra
assertion is preserved separately.

The KML slice verifies the upstream default point SYMBOL style through the real
OGR reader and in-memory GDAL filesystem. It remains unexecuted until the
resource-complete SDK qualification is reviewed. A fifth slice adapts actual GDAL
GeoTIFF creation and ElevationChunk sampling
with a 32 × 32 constant geographic HAE raster and an independent analytic height
oracle. It does not reproduce the original large fractal UTM regression.
Both new slices are source only, awaiting compile and runtime qualification.
The CPU 3D import slice writes an authored unit tetrahedron OBJ and calls the
real production ObjModelSpi/Model/Mesh. It checks four faces, twelve expanded
vertices, all XYZ coordinates, unit bounds and absence of invented materials.
The original upstream teapot OBJ/ZIP fixtures are absent from the pinned public
tree; this is not their scene-info regression. It does not exercise OpenGL.
Broad elevation sampling, 3D scene/texture and renderer tests are separate remaining
slices. A source/compile pass is not a native regression pass or a full-client
qualification.

## Run the offline guards

```sh
python -B -m unittest discover -s takx/kernel-regressions -p test_build.py
```

This command neither compiles Java nor loads native code. It verifies admission
failures and provenance, not the actual format behavior.

## Consume a reviewed SDK qualification

Use the **resource-complete** SDK component qualification, not the earlier
classes/native-only artifact. Supply its independently reviewed `complete.json`
hash. All SDK package files, dependencies and qualified Java tools are rehashed
before and after. The default phase only inspects inputs:

```sh
python -B takx/kernel-regressions/build.py \
  --sdk-proof /absolute/path/to/resource-complete-sdk-proof \
  --sdk-proof-sha256 REVIEWED_SHA256
```

Add `--phase compile --output /fresh/disjoint/output` for a Java-only compile
(2 MiB reservation). Add `--phase qualify` for a new headless, checked-JNI JVM
(256 MiB reservation, including the real native resource loader's extraction).
Both require a fresh output directory and retain the 2 GiB physical free floor.
There are no downloads, native rebuilds, automatic retries or hidden test skips.

The native run uses genuine `EngineLibrary` initialization and the existing
`KernelRuntimeSmoke` startup controls. Every requested format class must originate
from the reviewed component JAR. The final ELF map must contain all nine exact
packaged providers in the new owned loader directory; only previously qualified
JDK/host ELF identities may accompany them. Original native build paths and
shared SQLite/crypto backends are rejected. A failed command retains logs and a
failure receipt; all recorded outputs become read-only.

No native test has been run merely by adding this harness. Actual execution needs
the newly qualified SDK and enough reserved disk space; its receipt records the
tested slices and preserves the unqualified runtime/elevation/3D boundaries.

## Independent category processes

The prepared runner uses one checked-JNI JVM per category: DTED, MBTiles,
GeoPackage, KML, elevation and OBJ. Each gets a separate fresh fixture directory.
Processes run sequentially and share only the new run's stock resource-loader
extraction, bound to the exact SDK JAR digest. Existing proof caches are not used.
A category's failed assertion or JNI warning is recorded without hiding the
remaining categories; budget, deadline, input identity and provider failures stop
the run. Every category retains its own complete bounded log, exit code,
assertion marker and strict qualification result. JNI warnings always fail that
category. The existing 120-second bound applies to each process (six maximum).
No category outcome is claimed until this revised runner is actually executed.

## Observed qualification results

The source compiles against the genuine resource-complete SDK. Actual native
runs have **not qualified the complete suite**:

- Runtime 01 passed startup and basic native controls, then rejected an extra
  MBTiles SPI read-only assertion. The actual default IO provider ignores that
  option. The corrected test follows the upstream writable SPI roundtrip and
  separately checks direct native SQLite read-only behavior. Original failure
  receipt SHA256: `d25810b12995903c48391475f94bc2a919a1d698e3388d08dcf90dda32f30c5a`.
- Runtime 02 completed DTED/MBTiles and GeoPackage assertions, but GeoPackage
  encoding emitted checked-JNI warnings in GDAL `Driver_CreateCopy__SWIG_0`.
  It then failed KML parsing because the reduced GDAL provider lacks a KML
  reader. Elevation and OBJ were not reached. Receipt SHA256:
  `533ef2d28f507413e12a4c1ead02e12a6fb41bf34cbab35e8f68b9a808d4c914`.

The GDAL options-vector typemap calls Java enumeration methods without checking
pending exceptions. The reduced native build explicitly configures both
`--with-expat=no` and `--with-libkml=no`. These require real source/producer fixes
and new qualified artifacts; this suite does not replace providers, edit completed
SDKs or relax checked-JNI rules. The independent-process runner was prepared
after those failures and remains unexecuted. Compilation and offline provenance
checks are useful evidence, but do not substitute for passing native regressions.
