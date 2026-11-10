# Pinned TAKX consumers of public NASA WorldWind

This optional source staging tool applies one explicit import patch to a bounded
production consumer slice. It does not build a client or replace the declared
`gov.nasa:worldwind:2.2.1-TAKX-4` artifact. Blacksmith is test infrastructure and is
not an input to this production probe.

## Source contract

`sources.lock.json` pins all 20 consumed Java files and their staged hashes for:

| Official TAKX profile | Exact revision |
| --- | --- |
| 5.7 | `0b59a9bb2d0e90dc35c9edfff1c2056daab2b713` |
| 5.8 | `af54a3e1fe8796b6e109e2e5925dbef524ea7e31` |

The sources are from [TAK-Product-Center/TAKX](https://github.com/TAK-Product-Center/TAKX).
Nineteen files are identical across profiles; each profile's `ShapefileFeatureCursor`
is retained unchanged. The slice includes window, globe, annotation/image, marker,
shape cursor, input and layer adapters, the six earlier leaf consumers and two real
font helpers. These are selected production consumers, not an entire module.

The only modified file is `Platform/src/main/java/gov/takx/platform/globe/AOverlayLayer.java`.
`0200-takx-nasa-text-renderer.patch` replaces the JOGL `TextRenderer` import with
`gov.nasa.worldwind.render.TextRenderer`. No methods, features or sources are removed.
Stock NASA v2.2.1 at `9ccf6b8ed2ae452ef51e7b1739a7ffd4ef78a403` declares that actual
return type in `OGLTextRenderer.getOrCreateTextRenderer`. The consumer retains its
factory/cache and `begin3DRendering`, `setColor`, `draw`, `end3DRendering` calls.

NASA includes the real renderer implementation. Comparison against official JOGL
2.5.0 revision `70f62ca5d121e5e71548246d468b5e7baa5faf25` shows the same operations in
those directly called method bodies. This supports the import change; it does not
establish full implementation equivalence or runtime GL behavior.

## Staging

```sh
python3 takx/worldwind-consumers/stage.py \
  --source /path/to/pinned/TAKX --output /fresh/path/consumer-sources
```

The output must be absent. The tool verifies the exact HEAD, committed source
hashes and consumed worktree bytes, rejects symlinked inputs, checks the patch hash,
applies the actual patch to temporary copies and verifies every resulting hash.
Unrelated worktree files do not cause rejection. The original checkout is untouched;
failure does not publish a partial output. `staging-receipt.json` records all consumed
and staged hashes. Nothing downloads, compiles or loads native code during staging.

## Validation and its limits

Both unpatched profiles produced the same compiler error at AOverlayLayer's
assignment: NASA's TextRenderer cannot be converted to JOGL's TextRenderer. Separate
patched copies of the same 20-source slice then compiled with zero errors, producing
657 class files each. Javac selected 477 NASA sources from the complete frozen
1,726-source tree; this was not a full NASA or TAKX module compile.

The local investigation used JDK 17 (`--release 17 -proc:none`, 768 MiB, two active
processors, 180-second bound), the verified 2,697-class Kernel engine/port/annotation/
shared output from project revision `f1093e7a375299148f8f75c75a28438786a69465`, and its
35-JAR patched public classpath with SLF4J 1.7.30 explicitly replaced by TAKX-declared
2.0.17 and Jakarta annotation API 2.1.1 added. That includes actual public JOGL/gluegen
2.5.0 and project source-built modified GDAL 2.4.4 Java bindings. None was relabeled
as a newer SDK/private dependency. This is recorded local compile evidence; this
staging tool does not reconstruct that classpath or claim to ship a complete client
compiler recipe.

A subsequent probe used the complete project-standard-gdal-rgb WorldWind JAR
(3,241 classes from all 1,726 NASA sources plus the real palette helper), with an
empty sourcepath. Both patched 20-source profiles compiled with zero errors into
23 consumer classes each. This tests the packaged API, rather than relying on a
partially compiled NASA graph. The exact artifact identity and hashes are recorded
in `compile-evidence.json`. The project WorldWind variant is explicitly patched
for the current standard GDAL Java API and is not the unavailable TAKX-4 build.

After a real compile, inspect the consumer bytecode without initializing classes:

```sh
python3 takx/worldwind-consumers/check_bytecode.py --classes /path/to/compiled/classes
```

This requires NASA's factory and four renderer method references and rejects a JOGL
TextRenderer reference. It complements the source pins and genuine compile; it is
not a rendering test. Full WorldWind/GDAL integration, wider client compilation,
native contexts, glyph/rendering/cache behavior and client interoperability remain
separate acceptance gates. The unavailable TAKX-4 patch set is not reconstructed here.

Cheap offline integrity guards run in Unit CI, without any compiler or downloads:

```sh
python3 -B -m unittest discover -s takx/worldwind-consumers -p 'test_stage.py' -v
```

An additional exact-source staging test is opt-in; run once for each pinned checkout:

```sh
TAKX_SOURCE_DIR=/path/to/pinned/TAKX \
  python3 -B -m unittest discover -s takx/worldwind-consumers -p 'test_stage.py' -v
```
