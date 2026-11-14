# Experimental font JNI source control

This profile verifies and prepares three OpenJDK font source corrections. It
neither builds nor installs a runtime and grants no SDK or runtime acceptance.
The patch retains pending exceptions at HarfBuzz callback boundaries, checks font
read callbacks, and avoids Java fallback allocation while a read exception is
pending. Existing glyph-specific failure/recovery behavior is preserved.

The official `jdk-17.0.21+9` source revision is pinned in `inputs.lock.json`.
Its revision differs from the vendor runtime's recorded source revision. Matching
versions and bounded raster parity do not establish stock source/binary
equivalence. The patch is licensed under GPL-2.0-only with the Classpath exception;
`OPENJDK-LICENSE` is copied unchanged from that official source. The preparation
helper and guards use this repository's GPL-3.0-only license.

Default verification reads only the local contract and patch:

```sh
python3 prepare.py
python3 -B -m unittest discover -s . -p 'test_*.py' -v
```

Explicit preparation needs a previously cached official source tree and a fresh,
disjoint output directory. It authenticates all three inputs before writing,
applies the exact patch without fuzz, and checks every resulting source digest:

```sh
python3 prepare.py --phase prepare --source /path/to/cached/jdk17u \
  --output /path/to/new/font-source-control
```

Private Linux AMD experiments built all 63 font-module translation units afresh
and retained all 44 JNI exports. Six raster cases preserved pixel hashes and
metric bits, with zero candidate JNI diagnostics versus 426 vendor warnings.
Actual JNI callback controls covered three HarfBuzz cases and six FreeType cases,
including thrown read errors and recovery. These are scoped experiments; this
source-only helper does not reproduce or approve their native build. See the
parent qualification record for evidence and remaining renderer/runtime gates.
