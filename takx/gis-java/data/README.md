# Project GDAL data resources

Build a small data-only JAR from the already locked official modified GDAL
2.4.4 source archive. This project artifact is named
`uds-takserver-gdal-data.jar`; it is not the upstream `gdaldata:4.2.4` artifact,
a native GDAL runtime, a Kernel SDK or a working TAKX client.

## Build

Use Python 3.11 or later (`hashlib.file_digest` requires it). Reuse the GDAL
archive acquired for the
[GIS Java source recipe](../README.md), or download that same public
source input:

```sh
curl --fail --location --output /tmp/gdal-2.4.4-mod.tar.gz \
  https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/9f6893dd657feacc35ec5de03dad721c2e44170e/depends/gdal-2.4.4-mod.tar.gz
python3 takx/gis-java/data/build.py \
  --archive /tmp/gdal-2.4.4-mod.tar.gz --output /tmp/uds-gdal-data
```

The builder verifies the source archive's full SHA-256 and size before parsing
it or creating output. It also checks that this recipe and the GIS Java recipe
agree on the source input. It downloads nothing, extracts no source tree, runs
no build tools or native code, and accepts no SDK archive or SDK payload.

Use an empty output directory. The output contains the project JAR, an unchanged
copy of `GDAL-LICENSE.txt`, and `receipt.json` with source, recipe, lock, resource
and artifact hashes. The upstream data license also remains inside the JAR.
Data retains its upstream terms; the project's build code does not relicense it.

## Selection and determinism

The public source's `GNUmakefile` installs `LICENSE.TXT data/*.*`. The locked
archive's data directory contains exactly 92 regular files matching that glob.
`resources.lock.json` pins every filename, byte count and hash, plus the install
manifest and license. No SDK inventory is needed to select build inputs.

The JAR puts those files under `gdal/data/`, generates the sorted
`gdaldata.files` index including its own name, and retains the original source
license under `META-INF/licenses/`. The index follows the public native
[packaging rule](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takthirdparty/mk/gdal.mk),
which creates the index with `ls -1` after opening its output file.

Entry order, timestamps, permissions and manifest bytes are fixed. Entries use
ZIP's stored mode to avoid compression-library variation. The resulting data
JAR is deterministic and has no machine paths or build timestamps.

## Verify

Normal PR CI runs two offline integrity tests: a wrong-size input and a dummy
input with the exact locked size but the wrong SHA-256. Both must fail before
tar parsing or output creation. Neither test downloads anything.

Three real-source tests are opt-in and skipped in normal CI: source-byte
tampering, deterministic clean builds, and all 93 JDK resource lookups. They
passed locally against the locked public archive. To run them, set
`GDAL_DATA_ARCHIVE` and put JDK 17's `java` and `javac` on `PATH`:

```sh
GDAL_DATA_ARCHIVE=/tmp/gdal-2.4.4-mod.tar.gz \
  python3 -m unittest discover -s takx/gis-java/data -p test_build.py -v
```

The lookup probe loads only its own JDK test class and this data-only JAR. It
does not initialize GDAL, Kernel, TAKX or native libraries. A separate local
comparison against the official ATAK 5.5.1.8 SDK found all 93 data entries
byte-identical; that SDK was comparison evidence only and is not an input to
this build or test suite. No SDK bytes or third-party native binaries are
committed or republished by this recipe.
