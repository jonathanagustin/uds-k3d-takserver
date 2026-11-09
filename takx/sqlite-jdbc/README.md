# Opt-in source-built SQLite JDBC backend

This host-only recipe builds reviewed official Xerial sqlite-jdbc 3.54.1.0
(`2b39e1f8b315fbe11cdd7271ee929ae8f9638e07`) and official SQLite 3.54.1.
It does not adopt Xerial's bundled native binaries. The only dependency JAR is
the ordinary official SLF4J API 1.7.36, pinned by hash; no logging binding is added.

The locked 74 inputs total 15,814,646 bytes. Every input has SHA-256 and size;
Xerial files also have their Git blob identity, SQLite has its published
SHA3-256, and SLF4J retains its upstream Maven checksum. SQLite sources are
public domain; Xerial's Apache/BSD notices and extension source licenses remain
in the build inputs and packaged license resources. The root Xerial license
does not override extension licenses. SLF4J is MIT licensed.

## Build locally

Use native Linux x86_64, JDK 17, GCC, GNU make, Tcl, Perl, unzip, zip and patch.
The current acceptance host uses Temurin 17.0.21+9, GCC 14.2.0, make 4.4.1 and
Tcl 8.6.16. Exact tool binary hashes and version output enter the recipe key.
This is not a hermetic cross-platform toolchain or a bit-identical-build claim.

```sh
python3 takx/sqlite-jdbc/build.py \
  --java-home "$JAVA_HOME" \
  --cache /path/to/input-cache \
  --output /path/to/new-output
```

The input cache stores SHA256-named files. Add `--offline` to forbid downloads.
All fetched inputs must match the reviewed lock before staging. Native make
runs only `native OS_NAME=Linux OS_ARCH=x86_64`, at most two jobs and 240 seconds.
The staged build refuses curl/wget/Docker/Maven commands, so required sources
and the SLF4J API must already be verified before make runs. This guard prevents
upstream recipe downloads; it is not an operating-system network sandbox.

The one hash-pinned patch declares the existing RegisterExtensionFunctions
function before its injected call, which GCC 14 requires. It removes no SQL
features and suppresses no diagnostics. Both original and patched Makefile
hashes are checked. No multi-platform, Graal native-image or JPMS packaging runs.

## Outputs and reuse

- `sqlite-jdbc-host-source.jar`: all 59 ordinary Java sources, Java 8 target,
  with service/version/license resources, and no bundled native libraries.
- `native/libsqlitejdbc.so`: this host's own compiled JNI and SQLite core.
- `slf4j-api.jar`: the hash-locked public API dependency.
- `complete.json`: source/recipe/tool identity, artifact SHA-256 values and
  resolved native runtime-library hashes. This local completion record is not
  a signature, publisher attestation or a guarantee against a hostile writer.

The completion record is written only after real SQL acceptance passes.
Existing output must have the same key, exact artifact set/hashes and native
runtime closure. Unknown, corrupt and incomplete prefixes fail closed. Every
reuse reruns the SQL smoke test, including `/proc/self/maps` proof that the
process loaded this prefix's own JNI. An earlier scratch experiment is not a
completed recipe cache. Do not point this recipe at it or invent completion
metadata. To rebuild, choose a new absent output directory.

The recipe verifies source ID and required compile options, real parameterized
text/BLOB/int64/double/NULL queries, row types, transactions, savepoints,
read-only errors, persistence/user_version, update/delete LIMIT and retained
SQL extension functions. SLF4J's ordinary NOP warning is expected. The Java
consumer needs `-Dorg.sqlite.lib.path=/path/to/output/native` and
`-Dorg.sqlite.lib.name=libsqlitejdbc.so`, plus the two JARs on its classpath.
Verify the prefix through this recipe before using those paths.

Run non-native guards without fetching or compiling:

```sh
python3 -B -m unittest discover -s takx/sqlite-jdbc -p test_build.py -v
```

Android SQLite facade, CursorWindow, SQLCipher, SpatiaLite, engine JNI, ARM,
Android IPC and full TAKX acceptance are separate work. This backend supplies
none of them by implication. No default workflow or CI dispatch is added.
