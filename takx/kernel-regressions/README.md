# Public Kernel format regressions

This harness ports three real upstream test slices to the public-source desktop
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
  byte inserts, updates, disposal and read-only reopen. Opaque tile bytes are the
  upstream database test pattern; this does not test image decoding or every
  MBTiles schema implementation.
- GeoPackage 256 × 256 float gridded coverage, persisted nondefault offset/scale,
  terrain metadata controls and all decoded elevation samples.

KML, general elevation sampling, 3D and renderer tests are separate remaining
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
tested slices and preserves the unqualified KML/elevation/3D boundaries.
