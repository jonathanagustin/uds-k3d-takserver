# Kernel scene integration

This opt-in Linux amd64 profile builds the actual public Kernel **8.30.5**
`ASSIMPSceneSpi::create` path at official ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`. It produces a native subset;
full SDK assembly, JNI, rendering and TAKX acceptance remain pending.
Ordinary server tasks do not invoke this build.

## What passed

All 35 whole Kernel translation units compiled and linked with
`--no-undefined`. The real scene factory loaded a model and verified transformed
geometry, normals, V-flipped UVs, white material metadata, baked diffuse color on
every vertex, scene bounds, repeated construction/destruction and bad-URI
rejection. The process mapped the new subset, the exact verified Assimp library
and five named system runtime libraries; all provider files were hashed.
No Kernel implementation was replaced to satisfy these controls.

The recorded result is a fresh Kernel subset build using an explicitly resumed
GIS dependency producer. Its lineage remains separate from the current Kernel
recipe. It does not establish a fresh full dependency build, all raster-driver
behavior, target-image ABI suitability or security acceptance.

## Dependencies and supported formats

Locked inputs are official modified GDAL **2.4.4**, libkml **1.3**'s genuine
four-file minizip target, PROJ **4.9.1**, and the verified modified Assimp archive
named **4.0.1-mod**, whose library reports **4.1.0**, with zlib **1.3.1**.
The lock records source archives, patches and postimages. Whole source files
are compiled without stubs, symbol aliases or function garbage collection.

GDAL retains internally supplied raster codecs and self-contained formats.
It excludes PDF reading/writing, JPEG2000, MrSID/Kakadu/ECW/Lura, remote network
services, XML/libkml/OGDI, SQLite/GPKG/MBTiles/Spatialite and other optional
external databases/codecs. JPEG2000-compressed NITF is unavailable. The complete
configure arguments are locked; unknown options stop the build.

Minizip retains its real `libkml_unz*` API. A narrow CRC pointer-type patch
uses zlib's actual `z_crc_t`; the key algorithm stays unchanged. Controls cover
binary ZIP round trips, CRC corruption and correct/wrong legacy passwords.
These are functional checks, not cryptographic security claims.

## Run locally

Offline guards run without downloading or compiling native dependencies:

```sh
python3 -B -m unittest discover -s takx/kernel-scene -p 'test_*.py' -v
```

Build dependencies and the Kernel subset into a new directory:

```sh
python3 -B takx/kernel-scene/build.py \
  --output /private/new-kernel-scene-proof \
  --source /private/official-atak-checkout \
  --gdal-archive /private/verified-gdal-2.4.4-mod.tar.gz \
  --libkml-archive /private/verified-libkml.tar.gz \
  --proj-proof /private/completed-proj-proof \
  --assimp-proof /private/completed-assimp-proof
```

Reuse a completed, verified GIS producer without rebuilding it:

```sh
python3 -B takx/kernel-scene/kernel.py \
  --output /private/new-kernel-only-proof \
  --source /private/official-atak-checkout \
  --dependency-root /private/completed-gis-working-prefix \
  --dependency-proof /private/completed-gis-receipt-directory \
  --dependency-producer /private/preserved-producer-recipe-files \
  --gdal-archive /private/verified-gdal-2.4.4-mod.tar.gz \
  --libkml-archive /private/verified-libkml.tar.gz \
  --proj-proof /private/completed-proj-proof \
  --assimp-proof /private/completed-assimp-proof
```

Both paths verify source, configuration, tools, installed files, compiled
objects and actual minizip control output. New output must be outside the
repository and input/proof roots. Builds use one job, a 40-minute GDAL command
budget and 20-minute budgets for other stages. A 4-GiB output check runs between
commands; it is not a filesystem quota. Failures stop the run.

## Receipt and continuation limits

Fresh and resumed producers share a versioned receipt contract and preserve
producer recipe bytes. The consumer accepts the earlier complete receipt only
when all material facts verify. Schema exercises are explicitly marked and
rejected as producer acceptance. These checks establish local integrity, not
signed provenance or protection against a hostile metadata writer.

`resume.py` and `metadata.py` handle only the reviewed timeout and missing-tool
snapshots. Original failed outputs and complete snapshots remain preserved.
The completed continuation retained all 1,056 GDAL object bodies. An explicit
Python helper normalizes generated libtool metadata without a fake tool alias.
Historical resumed output always records `fresh_build: false`.
