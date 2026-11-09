# Real desktop SQLite vertical slice

This optional slice of `uds-desktop-android-compat` 0.1.0 implements actual SQL
behavior over the separately [source-built SQLite JDBC backend](../sqlite-jdbc/README.md).
It includes no binary and does not install anything into the server package.
It is not a renamed Android SDK or complete database compatibility layer.
All facade sources are original repository GPL-3.0-only code.

## Supported behavior

- SQLiteDatabase opens real plaintext files or in-memory databases with read/
  write/create modes. Read-only mode is enforced by the actual SQLite engine.
  The existing public adapter's NO_LOCALIZED_COLLATORS mode is accepted;
  Android's optional localized collation is not created.
- SQLiteProgram/Statement/Query use genuine 1-based prepared bindings for
  strings, BLOBs, integer64, doubles and NULL. CursorFactory runs **before**
  query execution so unchanged AndroidQueryStatement can bind BLOB/numeric
  parameters through SQLiteQuery. Rowids and affected counts are read while
  holding the same connection lock as their corresponding mutation.
- Cursors materialize actual typed JDBC rows into a local window. Count,
  before-first/after-last positions, backward moves, column metadata, NULL,
  empty text/BLOB and typed getters have real implementations. BLOBs are copied
  into/out of the window. The window has an explicit 16 MiB payload/row budget;
  exceeding it throws rather than silently dropping rows. This is not a total
  JVM heap cap or Android's ashmem/refill implementation.
- A transaction owns the connection lock until its outermost end. Nested
  unsuccessful scopes force outer rollback; nested success cannot commit early.
  Marking success twice, nesting after success and ending without an owned
  transaction fail. Other threads cannot execute on that connection mid-scope.
- SQLiteOpenHelper performs actual create/upgrade/downgrade/open lifecycle.
  Schema changes, data and user_version roll back together after failed upgrade.
  Readable fallback opens a real read-only connection when writable policy
  fails and the existing version matches. Relative names use the desktop
  Context files directory's databases subdirectory; absolute paths work too.
- Real corruption errors invoke the configured DatabaseErrorHandler. Closed
  cursor/statement/database operations fail; repeated resource close is safe.

The public Cursor/SQLiteCursorDriver surface is deliberately limited to the
methods used by this vertical slice. CursorDriver supplies a real backing-query
close callback, not Android's complete query/requery/deactivation protocol.
Android IPC/observers/cancellation/WAL configuration and the full exception
subtype hierarchy are not implemented. CRUD helpers currently require simple
SQL identifiers; SQL structure can instead be supplied explicitly with bound
selection values through rawQuery/compileStatement.

SQLCipher and SpatiaLite are **not** supplied. Key/rekey/cipher PRAGMA requests
are explicitly rejected; unknown SQLite pragmas are not evidence of encryption.
Native TAK EngineLibrary pointers, JNI database interop, spatial extensions and
existing encrypted files remain separate work. Do not redirect their calls to
an empty object or silently call a plaintext database equivalent.

## Authoritative contract and actual consumers

The source revision remains official
[TAK-Product-Center/atak-civ 9f6893dd657feacc35ec5de03dad721c2e44170e](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).
The runner exports unchanged tracked interfaces plus AndroidQueryStatement,
AndroidStatementAdapter, AndroidCursorAdapter, BindArgument and CursorIfaceAdapter
and executes those actual implementations against real JDBC/JNI. No engine
file is edited or a substitute Databases/Interop/Pointer class supplied.

Window conversion references are official AOSP Android 14 commit
`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`,
[CursorWindow JNI](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/jni/android_database_CursorWindow.cpp)
and [slot storage](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/libs/androidfw/include/androidfw/CursorWindow.h).
Tests include numeric prefixes/base-zero octal/hex and saturation, string NaN,
BLOB conversion errors, string-buffer terminators and normal percent-g-style
floating formatting. This Java formatter is not a claim of bit-identical libc
formatting for every floating rounding tie or a full Android ABI.

Actual remaining source boundaries are visible: CursorIfaceAdapter does not
close its delegate and its replacement-window path cannot generally refill an
already exhausted delegate. The test explicitly closes that delegate; it does
not conceal the upstream lifecycle issue. AndroidQueryStatement's source counts
question marks textually, which is not a complete SQL placeholder lexer.
AndroidDatabaseAdapter and the TAK-specific SQLiteOpenHelper pull native
Databases/Interop/IOProvider initialization; the isolated test does not pretend
those whole closures execute. The independently implemented Android helper is
what the direct schema lifecycle tests exercise.

## Run against an already accepted source-built backend

Use trusted JDK 17 java/javac on PATH. Build and verify the separate recipe first;
then supply its **completed** prefix and source cache:

```bash
python3 takx/compat/test-sqlite.py \
  --source /path/to/clean/pinned/atak-civ \
  --backend /external/sqlite-prefix \
  --cache /external/sqlite-source-cache
```

The runner requires existing completion metadata and verifies its three exact
artifacts and runtime dependencies. It reruns the source recipe **offline** in
completed-cache mode, including its real SQL smoke, before loading JNI. Unknown
or changed completion metadata fails; the test does not start a native build.
It compiles the complete local compat sources and unchanged upstream consumer
subset with Java 11 compatibility and bounds the JVM test to 60 seconds. Temporary
SQL files, class outputs and connections are cleaned up.

Acceptance covers factory-before-query typed bindings; actual upstream statement/
query/window adapters; rowid/change counts; cursor movement and types; nested
rollback/commit and thread isolation; helper version rollback/read-only fallback;
native corruption/read-only errors; resource bounds and lifecycle. Assertion
counts are test checks, not implemented APIs. Passing these tests and the full
public port compile does not establish full engine or TAKX client acceptance.
