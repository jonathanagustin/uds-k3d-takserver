# Public Kernel format regressions

This harness adapts real upstream test slices and bounded authored 3D fixtures to the public-source desktop
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
OGR reader and in-memory GDAL filesystem. A fifth slice adapts actual GDAL
GeoTIFF creation and ElevationChunk sampling
with a 32 × 32 constant geographic HAE raster and an independent analytic height
oracle. It does not reproduce the original large fractal UTM regression.
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
(256 MiB reservation on the output filesystem, including the real native resource loader's extraction).
Both require a fresh output directory and retain the 2 GiB physical free floor in `/workspace`. A separate executable output filesystem is reserved independently; it does not waive that workspace floor.
There are no downloads, native rebuilds, automatic retries or hidden test skips.

The native run uses genuine `EngineLibrary` initialization and the existing
`KernelRuntimeSmoke` startup controls. Every requested format class must originate
from the reviewed component JAR. The final ELF map must contain all nine exact
packaged providers in the new owned loader directory; only previously qualified
JDK/host ELF identities may accompany them. Original native build paths and
shared SQLite/crypto backends are rejected. A failed command retains logs and a
failure receipt; all recorded outputs become read-only.

Actual execution needs a reviewed resource-complete SDK and enough reserved disk
space. Its receipt records each tested slice; broader elevation, scene, renderer
and full-client acceptance remain separate.

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

Earlier genuine native attempts did not qualify the complete suite:

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

Those earlier artifacts had an unchecked GDAL options-vector typemap and no KML
reader. A later independently reviewed composed SDK includes genuine GDAL/JNI
source fixes, KML support, a reduced-driver initialization profile and the OBJ
small-buffer fix. This harness does not replace providers, edit completed SDKs
or relax checked-JNI rules.

On 2026-11-13, the revised independent-process runner at `d440be0` qualified all
six categories against that retained SDK. SDK receipt SHA256:
`f8436e590294cf38683dded113fb250d5301a4146bbae10a278ee361de512a1d`.
Fresh regression receipt SHA256:
`abf15e67cd827ebf76edb0923a2c8c9b36b1479dfdda945d9987485deaf8b253`.

| Category | Assertions | Checked-JNI process |
| --- | ---: | --- |
| DTED discovery | 13 | PASS |
| MBTiles | 29 | PASS |
| GeoPackage gridded coverage | 65545 | PASS |
| KML point style | 5 | PASS |
| Analytic GDAL elevation | 13 | PASS |
| Two authored CPU OBJ imports | 39 | PASS |

Every category exited zero, passed the unchanged strict native/JNI diagnostic
gates and mapped all nine exact packaged native providers. The API-only SLF4J
framework notices remain visible; this is not a claim of globally silent startup.
The fresh attempt used an executable tmpfs output and retained the workspace's
2 GiB free floor; aggregate compile/failed-attempt/current outputs used
216412160 allocated bytes, below the 256 MiB cap. Its first attempt passed DTED
assertions but rejected the exact qualified `bin/java` executable because the
harness allowed JDK libraries only. That failed receipt and cache-restoration
provenance remain preserved; the fix admits only the independently hashed Java
tool, not arbitrary JDK binaries.

This qualifies these adapted CPU format slices against the named component. It
does not qualify a new SDK packaging recipe, renderer, original upstream teapot
assets, or full client.

The OBJ category keeps the original authored tetrahedron and also imports a compact
version without its comment. Both use the same independent mesh/coordinate oracle;
the smaller valid input exercises the production parser's small-buffer growth boundary.
This remains authored CPU parser coverage, not the absent upstream teapot test.
