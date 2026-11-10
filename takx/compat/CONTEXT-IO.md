# Desktop Context filesystem and resource IO

This extends the existing concrete desktop Context, resource catalog and asset
backend. It does not emulate installed Android APKs, arbitrary content providers
or an Android package database. The Java code is original GPL-3.0-only. It uses
the separately accepted real `android.net.Uri`, `Parcel` and `Parcelable` sources;
no placeholder URI or parcel implementation is supplied here.

## Database paths and own-package metadata

`getDatabasePath(name)` returns a validated filename under the real app-data
`databases/` directory, creating that directory but not a database file. Names
must be a single private filename; traversal, separators and absolute names fail.
Existing path/root symlinks may not escape that private directory. This provides
filesystem location, not a SQLite implementation or a claim that a database has
been opened. The database/runtime layer remains separately validated.

`getPackageManager().getApplicationInfo(getPackageName(),0)` returns fresh
own-package metadata with a real `nativeLibraryDir`. By default Context creates
its private app-data `lib/` directory. The directory can be empty: no native
libraries are invented or claimed to be installed. Setting JVM property
`uds.desktop.nativeLibraryPath` selects an explicitly configured absolute,
existing native library directory, resolved to its real path. Unknown packages
throw `NameNotFoundException`; nonzero flags are unsupported. Returned metadata
cannot mutate the manager's internal record. No Android APK scanning, signing,
permissions or other PackageManager surface is advertised.

## ContentResolver streams

`getContentResolver().openInputStream(uri)` supports real streams for:

- `android.resource://package/raw/name`
- `android.resource://package/<numeric-id>` for a raw resource
- local absolute regular-file URIs, with no authority or `localhost`

Resource names/IDs must exist in the existing explicit UTF-8 classpath catalog,
including its known additional package entries. Numeric IDs must belong to the
URI's package; another package cannot reuse the same ID. Wrong resource type,
missing data, malformed URI/range, unknown package, remote file authority or
query/fragment fails with `FileNotFoundException`. `content://` and other schemes
have no registered desktop provider and fail explicitly; they never return an
invented empty stream. File URIs use ordinary OS file permissions and are not
restricted to app-data; private database paths and classpath resources have their
own bounds. Directories and special files are not supported file-stream inputs.

Streams belong to the caller. Directory-backed and JAR-backed raw resources use
the same bounded resource opener as assets, so catalog files cannot follow a
symlink outside their declared classpath root. Text helpers continue to close
streams that they open internally. No native Android binary resource table is
read; the catalog remains the actual resource source.

## Assets.list and stream ownership

`Assets.list("")` and `list(subdirectory)` enumerate sorted immediate children
from real local URLClassLoader directory/JAR roots and the system classpath when
it is actually in the loader chain. Results union multiple exposed roots. A JAR
need not contain explicit directory entries: child paths derive from its real
entries. A real absent directory or file path has no children. A ClassLoader
that does not expose such roots cannot pretend to enumerate them and fails.
Implicit manifest-only dependency roots and remote class-loader backends are not
advertised; put supported asset roots explicitly on the classpath.

Asset paths reject traversal, empty segments, absolute/drive paths, backslashes,
control characters and percent-encoded path forms. Spaces and Unicode literal
filenames remain usable. Filesystem roots, directories and files are checked
against real paths, rejecting escaping asset-root or descendant symlinks.
Directory/catalog checks cover static filesystem bounds, not an atomic defense
against another process concurrently replacing app-owned path components.
JAR traversal entries fail enumeration. `open` resolves the selected URL to a
declared local backend; JAR streams own their opened JarFile and release it on
close. Closing one stream does not close another caller's independent stream.

## Local checks and limits

The local run passed the existing 61 Context checks plus 65 new checks using real
private directories, files, classpath catalog data and JARs without directory
entries. Tests cover database/root symlinks, own/unknown package metadata,
explicit native directories, own/multipackage resource IDs, file URIs, missing
providers, traversal, escaped resource/asset symlinks, sorted children and closed
file/JAR stream behavior. No application native library, SQL engine, network
provider or Android APK is fabricated to manufacture acceptance.

After the accepted Uri/Parcel prerequisites are present in this checkout:

```sh
python3 takx/compat/test-context-io.py
bash takx/compat/test-context.sh
```

For isolated incremental review, `test-context-io.py --support-root /path/to/compat`
and `TAKX_COMPAT_SUPPORT_ROOT=/path/to/compat` let these tests read the actual
accepted prerequisite source tree without copying or changing it. Both compile
for Java11 using a JDK, write only temporary outputs and run offline. The Python
check bounds compiler/runtime execution. Existing public-port compilation was
also tested with a read-only archive of those real accepted prerequisites plus
this slice; full engine/client/runtime acceptance remains separate. There is no
new default CI job, deployment behavior, Environment or Xml implementation.
