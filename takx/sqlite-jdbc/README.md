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
runs only `native OS_NAME=Linux OS_ARCH=x86_64`, one job and 300 seconds. The dedicated output/cache is limited by a between-stage 1 GiB size check (not a filesystem quota).
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
  resolved native runtime-library hashes, the complete actual SQLite object-definition inventory and final JNI export policy. This local completion record is not
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

## Plain JDBC and native SQLCipher coexistence

The host JDBC adapter remains genuine plain SQLite **3.54.1**. Native Kernel’s encrypted database profile uses genuine SQLCipher **4.5.7** / SQLite **3.45.3**, linked with OpenSSL **3.5.9**. These are distinct implementations and capability profiles; this change does not give JDBC SQLCipher encryption.

Upstream already compiles Linux x86_64 objects with hidden visibility. The recipe additionally enforces a final GNU ld map exporting only actual `Java_org_sqlite_*`, `JNI_OnLoad` and `JNI_OnUnload` entrypoints. It compares the complete defined-symbol union from the real compiled `sqlite3.o` (including retained extensions) against the final dynamic symbol table: no backend definition may escape or be imported. Xerial links this object directly; no fictitious SQLite archive is claimed. The link retains all upstream features and uses `--no-undefined`; actual DT_NEEDED/TEXTREL and runtime-library checks reject a shared SQLite or crypto backend.

Optional same-process acceptance uses the existing normative `native-crypto` proof and its modern SQLCipher group:

```sh
python3 takx/sqlite-jdbc/build.py \
  --java-home "$JAVA_HOME" --cache /private/source-cache --output /private/new-output \
  --offline --crypto-proof /private/completed-native-crypto-proof \
  --modern-proof /private/completed-native-sqlcipher-proof
```

This verifies the actual crypto producer recipe, source/installed/output inventories, build tools and mapped libraries. Fresh real-JVM processes load JDBC→modern and modern→JDBC with `RTLD_NOW | RTLD_GLOBAL`. Each executes the unchanged complete JDBC SQL controls, real modern AES/encrypted-write/reopen/wrong-key controls, then JDBC SQL controls again. It checks native backend version identities, global symbol lookup and actual mapped paths. The owned C test driver invokes real JDK JNI; it provides no replacement JDBC/SQLite/SDK classes or APIs. JVM `-XX:-UsePerfData` disables unrelated temporary performance mapping so receipt hashing can inspect persistent loaded files after shutdown. The first attempt’s successful SQL assertions and stopped ephemeral-map metadata evidence were preserved privately; no completed receipt was inferred from it.

To replay a completed coexistence proof, set `TAKX_SQLITE_JDBC_PROOF`, `TAKX_SQLITE_CRYPTO_PROOF` and `TAKX_SQLITE_MODERN_PROOF` to those three verified prefixes, then run the same unittest command. Defaults remain offline guards without compilers, native execution or downloads. Existing CLI arguments and the three-artifact consumer contract remain supported. Coexistence does not establish EngineLibrary initialization, full native Kernel/JNI, completed CommonCommo or TAKX acceptance.
