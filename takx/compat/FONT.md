# Desktop text measurement

This slice of `uds-desktop-android-compat` 0.1.0 implements the text-measurement API used by the public Kernel 8.30.5 port module. It is independently implemented with JDK Java2D; it is not the upstream AndroidPort artifact or an Android SDK replacement.

`Typeface` resolves font families and styles through the JDK. `Paint` measures text using Java2D font layout and obtains real signed ascent, descent and maximum bounds. Its character-width method uses left-to-right glyph advances. Style, alignment, antialiasing and ARGB state are retained; this slice exposes no Canvas drawing API. `PorterDuff.Mode` supplies the 18 blend-mode values used by the real Kernel marshal registry, without claiming a compositor implementation.

Run with JDK 17 and the clean, pinned official ATAK checkout:

```bash
ATAK_SOURCE_DIR=/path/to/atak-civ ./takx/compat/test-font.sh
```

The runner verifies the source revision and consumed tracked files, compiles the real upstream `Font`, `FontMetrics` and `DisplaySettings` with Java 11 bytecode, and runs headless tests. It checks all four font styles, proportional and Unicode measurement, signed metrics, range failures, fractional and zero sizes, actual upstream multiline baseline spacing and live relative-scale changes. It downloads nothing and leaves no build outputs in the repository.

Font availability and the JDK's shaping/metrics can differ from Android Skia and the unpublished desktop runtime. Complex bidirectional character-width equivalence and pixel-identical label rendering are not established. Font size accepts finite nonnegative values; invalid sizes fail explicitly. The engine's broader Paint/Canvas/Matrix APIs remain outside this slice. Full Kernel and both TAKX clients still require further implementation and runtime tests.

The ordered `0001-kernel-remove-unused-colorfilter-import.patch` removes an unused Android `ColorFilter` import from official ATAK revision `9f6893dd657feacc35ec5de03dad721c2e44170e` (Kernel 8.30.5). No color-filter stand-in is supplied and no rendering behavior is removed. Apply that exact source patch before compiling the complete port/marshal integration; include its hash in any resulting build identity.
