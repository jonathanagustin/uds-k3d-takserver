# Desktop compatibility prototype

`uds-desktop-android-compat` 0.1.0 is a small Java desktop compatibility layer for the pinned public TAK Kernel. It is optional research code, not AndroidPort 6.1.2, an Android SDK, a packaged TAKX client, or a replacement for the complete Kernel runtime. Nothing in the server deployment imports or installs it.

The implementation uses JDK `BufferedImage`, ImageIO, Java2D fonts, classpath streams and real filesystem persistence. Its supported surfaces are documented separately:

- [Bitmap pixels, decoding and upstream marshaling](BITMAP.md)
- [Coordinate and rectangle primitives](GEOMETRY.md)
- [Font selection and text measurement](FONT.md)
- [Context, resource catalogs and persistent preferences](CONTEXT.md)

Most sources are original repository code under the root GPL-3.0-only license. RectF adapts the same pinned official public port implementation, retaining its Apache-2.0 notice and license; see [geometry provenance](GEOMETRY.md). The tests compile upstream code from the separately checked-out official `TAK-Product-Center/atak-civ` revision `9f6893dd657feacc35ec5de03dad721c2e44170e`. Upstream code remains in that checkout; no private SDK JAR is included.

## Run the behavioral checks

Put JDK 17's `java` and `javac` on `PATH`; tests compile with `--release 11` to match the public Kernel. Set `ATAK_SOURCE_DIR` to the clean pinned official checkout, or initialize the existing `upstream/atak-civ` gitlink with Git LFS smudging disabled. These Java sources do not need LFS archives.

```bash
export ATAK_SOURCE_DIR=/path/to/atak-civ
./takx/compat/test-font.sh
./takx/compat/test-bitmap.sh
./takx/compat/test-context.sh
python3 takx/compat/test-geometry.py --source "$ATAK_SOURCE_DIR"
```

The font and bitmap tests exercise real upstream wrappers and the marshal registry. Context tests include separate JVM restarts, concurrent JVM writers and concurrent threads using different Context objects. Tests use temporary directories and do not download inputs, change upstream files, load native graphics or start clusters.

## Compile the complete public port module

The combined prototype compiles all 77 public port sources and six annotation sources with Java 11 compatibility. This resolves that module's earlier 97 compiler errors. It does not compile the engine or either TAKX application.

Download the five public JARs from the exact official URLs in [port-classpath.lock.json](port-classpath.lock.json), placing their named files in one directory. The runner checks every SHA-256 and uses only those files, even if the directory contains other JARs. It uses JOGL/gluegen 2.5.0 and SLF4J 1.7.30, plus Commons Text 1.15.0 with its Commons Lang 3.20.0 runtime dependency. The newer Commons Text replaces the earlier investigation's 1.9 compile-only coordinate; the actual upstream HTML utility is exercised with the complete transitive pair.

```bash
python3 takx/compat/test-port.py \
  --source "$ATAK_SOURCE_DIR" \
  --classpath-dir /path/to/verified-jars
```

The runner verifies the upstream revision and clean consumed sources, copies only tracked Java files to a temporary directory, applies the hash-checked unused-import patch there, compiles the complete module and adapters, and exercises all 18 blend-mode marshal round trips plus the real HTML utility. Its JSON result records source, adapter, classpath and patch hashes. Existing upstream deprecation/unchecked warnings remain visible. The native CommonCommo cache and original checkout are untouched.

## Remaining acceptance

Both official TAKX 5.7 and 5.8 remain candidates; prefer 5.8 after actual full-client acceptance. Full Kernel engine compilation, SQLite, broader graphics/Canvas/Matrix/URI APIs, native GIS/GL dependencies and TAKX resource catalogs still need implementation or compatible public inputs. These limited APIs deliberately do not pretend to support Android services, binary resources or the complete graphics surface.

No live map rendering, GL recovery, enrollment, CoT exchange or TAKX desktop session is established by the port-module checks. Follow [issue 376](https://github.com/jonathanagustin/uds-takserver/issues/376) for the prototype and its remaining runtime gates. The normal server CI does not download or compile this opt-in component.
