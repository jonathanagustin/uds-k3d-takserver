# Desktop context and resources slice

This original, limited implementation supplies concrete desktop `android.content`
classes for the public TAK resource wrappers. It is part of the proposed
`uds-desktop-android-compat` 0.1.0 component. It is **not** upstream AndroidPort
6.1.2, an Android framework implementation, or acceptance of full Kernel or TAKX.
No upstream implementation code or private artifact was copied.

The public consumers are pinned to ATAK revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`, notably
[`JavaResourceManager`](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/port/src/jre/java/gov/tak/platform/commons/resources/JavaResourceManager.java),
[`ResourceManagerBase`](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/port/src/main/java/gov/tak/platform/commons/resources/ResourceManagerBase.java),
and the adjacent asset wrappers. TAKX sets the `TAK_APP_DATA_PATH` Java system
property before Kernel initialization. The public Kernel changelog documents
consistent files/cache paths and preferences under the files directory.

## Context and preference contract

`new Context()` selects the absolute `TAK_APP_DATA_PATH` system property, then
the environment variable, otherwise `${user.home}/.tak/desktop`. Set the property
before constructing any context. Files and cache use `files/` and `cache/`
under the canonical app-data directory. Multiple contexts share those paths.
A symlinked child directory escaping that root is rejected. The explicit
`Context(Path, String, ClassLoader)` constructor supports isolated callers.
`uds.desktop.package` sets the default package name; its default is
`gov.tak.desktop`. These names do not invent application resources.

Only `MODE_PRIVATE` preferences are supported. They live in
`files/shared_prefs/<name>.properties`; names cannot contain traversal or path
separators. Values support strings, string sets, integers, longs, floats and
booleans. Wrong-type reads throw `ClassCastException`. Null string/set values
remove a key. Clear runs before the editor's additions. Returned stored sets
and maps are immutable copies. Registered listeners receive changed keys after
successful persistence, synchronously on the caller's thread; callers must
unregister them when finished.

Every read reloads the file. Commits hold an OS file lock, merge against the
latest data and atomically replace a flushed temporary file. Tests exercise
process restart and concurrent JVM writers, not just in-memory reuse.
`commit()` returns false on I/O or corrupt-file failure; reads of corrupt files
throw `UncheckedIOException`. `apply()` is deliberately synchronous and throws
`UncheckedIOException` if persistence fails. This differs from Android's
asynchronous `apply()`. Storage is a typed desktop properties format, not
Android XML or encrypted storage. Atomic-move support is required. Process
restart persistence is tested; abrupt power-loss durability is not claimed.
Preferences must not be edited concurrently through unrelated filesystem tools.

## Classpath catalog

A trusted class loader can supply one UTF-8 file:
`META-INF/uds-desktop-resources.properties`. Its entries explicitly map
`package/type/name` to classpath paths. For example:

```properties
test.app/string/greeting=res/greeting.txt
test.app/array/labels=res/labels.properties
test.app/color/accent=res/accent.txt
test.app/raw/payload=res/payload.bin
```

Supported types are `string`, `array`, `color`, and `raw`. String files are exact
UTF-8 text (including any trailing newline); formatted strings use Java
`String.format`. Array files are UTF-8 properties containing `count=N` and
exactly the keys `0` through `N-1`. Color files contain `#RRGGBB` or `#AARRGGBB`.
Raw resources return the actual classpath bytes. Array results are fresh copies.

IDs are nonzero integers assigned by sorted catalog key. They remain consistent
between instances with the same catalog, but are not persistent Android `R`
constants across catalog changes. Both separate name/type/package arguments and
`package:type/name` work. An unknown identifier lookup returns zero; retrieving
an absent ID, wrong type, malformed value or missing file throws
`Resources.NotFoundException`. Missing catalog means no resources, never
placeholder content. Multiple catalogs, duplicate entries, unsupported types
and missing mapped files are rejected explicitly.

Assets are actual streams under `assets/` on the supplied classpath. Missing
assets throw `FileNotFoundException`. Callers own and close asset/raw streams.
Paths use ASCII letters, digits, underscores, dots, hyphens and slashes; absolute
paths, empty segments, `.`/`..`, backslashes and encoded paths are rejected.
Classpath roots and their contents are trusted; this is lexical traversal
protection, not sandboxing an adversarial class loader or a concurrent local
filesystem attacker.

Drawable/font/XML decoding, Android binary resource tables, configuration/theme
selection, resource overlays, services, broadcasts, permissions, SQLite and other
Context methods are not implemented. There are no null-returning service stubs.
The public portable resource wrappers compile against this slice, but consumers
requesting unsupported types or APIs need further real implementations.

## Verification

Run with a JDK 17 or newer:

```sh
bash takx/compat/test-context.sh
```

The runner uses `javac --release 17` and temporary output only. It checks real
resource bytes, identifier consistency, UTF-8 strings/arrays/colors, stream
reads, malformed resources, traversal, canonical directories, typed preferences,
immutable snapshots, clear/remove/listeners, corruption, separate reader/writer
JVMs and four concurrent writer JVMs. Each child JVM has a 30-second timeout.

The resource interfaces and eight public wrapper/interface source files also
compiled locally against this implementation at the pinned ATAK revision.
This is a scoped source-compatibility check; full AndroidPort, full Kernel,
native libraries, and both TAKX clients remain unaccepted.
