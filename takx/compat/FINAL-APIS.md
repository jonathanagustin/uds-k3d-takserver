# Final desktop API contracts and filesystem validation

This slice supplies the remaining API shapes needed by the pinned public
Kernel's Java sources. UDS remains a server deployment; these adapters are an
optional desktop foundation. Successful Java compilation and focused runtime
checks do not establish a working TAKX client or native map renderer.

## Reference boundary

[final-api-sources.lock.json](final-api-sources.lock.json) pins Android
`android-14.0.0_r1`: frameworks/base
`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`, libcore
`4ce63484144d6e245ad55e7a0027ea075cbd804c`, and Skia
`1145116447a46710a65e3a5deabb7d7c752af5ea`. The exact Java declarations,
Bitmap native implementation and SkConvertPixels copy path were reviewed.
Sources remain external; the runner verifies their hashes without downloading.
Libcore URLs return base64, which must be decoded before the hash check.

The behavior tests execute this desktop implementation against source-derived
contracts and real image/filesystem fixtures. They do not run Android JNI.
The separate [native-pixel tests](NATIVE-PIXELS.md) execute extracted pinned Skia
integer formulas as an additional format-conversion oracle.

## Graphics behavior

- `ARGB_4444` is a deprecated creation request. It resolves to `ARGB_8888`
  storage; configuration reporting, allocation/capacity checks, decoder output,
  scaling and copy use the actual resolved format. No four-bit format is
  claimed.
- `Bitmap.copy` produces independent storage and respects requested mutability.
  Same-format owned copies preserve physical bytes, including alpha bytes hidden
  by an opaque metadata hint. Cross-format copies convert semantic pixels.
  Borrowed Java2D images copy into the documented owned, straight-alpha format;
  they do not acquire an Android premultiplied storage contract.
- `setHasAlpha` changes an owned RGBA view's interpretation without rewriting
  pixels. It also works on immutable bitmap metadata. RGB565 ignores this hint,
  as documented by AOSP. Opaque ALPHA8 metadata is explicitly unsupported,
  including copies from opaque sources to ALPHA8. Borrowed view metadata
  mutation remains unsupported. Recycled operations fail.
- `Canvas.drawColor(int)` fills the software surface using SRC_OVER, including
  transparent no-effect and partial-alpha composition. This adds no clip,
  native renderer or alternative blend-mode API.
- `Paint(Paint)` copies every currently supported text/drawing property. The
  underline and strike-through constants supply the masks consumed by upstream
  `MapTextFormat`; they do not add unsupported text decoration rendering.
- `BitmapFactory.decodeStream(InputStream)` decodes through ImageIO and leaves
  the caller's stream open. Deprecated `inDither`, `inPurgeable`,
  `inInputShareable` and `inPreferQualityOverSpeed` have no decoder effect on
  the pinned Android release. `requestCancelDecode()` still sets `mCancel`,
  while decoding proceeds, matching the pinned deprecation contract.
- `inTempStorage` is **not** an ignored deprecated option in Android 14. A
  non-null request explicitly fails before reading the stream because ImageIO
  does not use that supplied scratch allocation.
- Nonzero `inDensity` explicitly fails for image creation: density metadata is
  meaningful even when scaling is disabled or source/target densities match.
  Bounds-only queries return before density scaling/metadata, as in the pinned
  native decoder. `inTargetDensity` alone does not request scaling. Resource
  density, nine-patch and density-aware drawing remain outside this slice.

## Real Unix metadata

`android.system.Os.stat` uses NIO's Unix attribute view, follows symlinks and
returns actual `st_dev`, `st_ino`, `st_rdev`, `st_uid` and `st_gid`. These are the
five fields consumed by the pinned Kernel VSI handler. It supplies no invented
UID/GID, device or inode fallback and makes no claim to expose full `struct stat`.
The empty path returns ENOENT rather than accidentally resolving Java's current
directory.

Only typed NIO missing-file, access-denied, not-directory and filesystem-loop
exceptions map to Linux errno values 2, 13, 20 and 40. Some NIO providers report
not-directory and loop failures as generic `FileSystemException`; those remain
`UnsupportedOperationException` with the original cause. Localized exception
messages are not parsed into guessed errno values. Unsupported Unix attribute
views also fail explicitly. Null/path-syntax programming errors retain their
Java exceptions. `ErrnoException` exposes the function, errno and original cause;
full libcore strerror formatting and the rest of `android.system` are unimplemented.

The direct test compares all five fields to independent Python `os.stat` values
for regular files, directories, hard links, symlinks and `/dev/null`, then checks
missing/dangling/empty paths, permissions, loops and non-directory parents.
The permission fixture is exercised as an unprivileged process and explicitly
skipped if the test process is root.

## Unchanged Kernel consumer

The optional integration check loads the actual, unchanged
`VSIFileFileSystemHandler`, `VSIJFileFilesystemHandler`, `VSIStatBuf`,
`FileSystemUtils` and default IO provider from the frozen complete Kernel build
at official revision `9f6893dd657feacc35ec5de03dad721c2e44170e`.
It calls the public `FileSystemUtils.setMountPoint` with a temporary directory,
which limits discovery and migration to that mount. No upstream method, class
or native symbol is replaced by a test stub.

The check exercises actual `.stat` template metadata, file reads and writes,
symlink/directory/file stat, missing files and prefix rejection. The upstream
handler intentionally reports a virtual policy: identity comes from its `.stat`
template, block size is 512, and time values are milliseconds. These are
assertions about the unchanged upstream handler, not POSIX stat equivalence.
The test does not call native filesystem registration or invoke GDAL.

## Run the checks

Use JDK 17 with Java 11 source compatibility, Python 3 and a Unix filesystem.

```sh
python3 takx/compat/test-final-apis.py --source-dir /path/to/pinned-api-references
python3 takx/compat/test-final-apis.py --source-dir /path/to/pinned-api-references \
  --kernel-proof /path/to/fresh-frozen-kernel-compile
```

**The full-engine compile result is local investigation evidence.** This
repository does not yet provide its complete compiler recipe or a portable
25-JAR input recipe. The checked-in port runner and individual API/source
recipes remain independently runnable. Supplying `--kernel-proof` consumes an
existing local compile proof; it does not rebuild or independently reproduce
the complete engine.

The optional proof directory contains `inputs.json`, `result.json`, compiled
`classes/` and frozen `stage/` sources from the complete engine compile probe.
The runner checks the upstream revision, every frozen source and original JAR
hash, and an exact match between frozen and current adapter source inventories
before using those compiled classes. Without that argument it explicitly reports
that Kernel VSI integration was not run.

The reviewed complete compile retained all 862 engine, 77 port and six annotation
sources (945 upstream), plus 59 adapters, with all 25 original classpath JAR hashes:
1,004 source files, zero compiler errors and four warnings. Of the 945 upstream
files, 944 match the pinned revision byte-for-byte; `ColorBlendModeMarshal.java`
has only the existing, hash-checked unused-import removal patch. All 862 engine
files remain byte-for-byte unchanged. The original port
runner remains available separately. This is compilation evidence, not full
Kernel, TAKX, GL, GIS or native runtime acceptance.

Remaining gates include runnable TAKX application packaging/resources, compatible
native GIS/GL/Kernel linkage, actual map rendering and recovery, enrollment and
CoT exchange, broader graphics and density behavior, and complete native/database
interop. SQLite's separate real-JNI checks do not establish those client gates.
