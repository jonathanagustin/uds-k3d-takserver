# Public-source Kernel component package

The local qualification passed four fresh JVM runs, including package relocation, with zero JNI warnings and all nine native providers loaded from stock extraction. It also passed the missing-resource negative control. The two earlier failed attempts remain preserved separately.

This opt-in Linux amd64 profile assembles the genuine Kernel **8.30.5** Java/JNI component and qualifies its real `EngineLibrary` resource loader. It uses the fresh native component producer, exact Java class inventory and verified dependency producers from `kernel-native`. It builds no native library and substitutes no TAKX release version.

The package contains one Kernel class/resource JAR, separate third-party JARs, the original Kernel and generated JNI headers, exact source notices and a version/ABI manifest. The manifest lists every class, header, notice, native resource and dependency JAR. The bundle includes no proof logs, runtime databases or private keys. Headers are the selected Kernel/JNI headers; this qualification does not establish a complete third-party C++ development kit.

The owned patch changes the real Linux64 preload list to the nine available providers in dependency order: GLdispatch, GLESv2, LAS, LAS_C, GDAL, GDALallJNI, Assimp, Core and KernelJNI. It also reports a missing required Linux resource. No proprietary placeholder library is supplied. Crypto, SQLCipher, Cesium and the other static dependencies retain the qualified native producer's actual ownership and export policy.

GDAL's genuine Java initializer calls `System.loadLibrary("gdalalljni")` even after EngineLibrary loads its resource. Start the JVM with `java.library.path` pointing to EngineLibrary's extraction directory. The manifest records its template: `${java.io.tmpdir}/takkernel/engine/<JAR MD5>/lib/linux64`. MD5 is the upstream cache-directory locator; SHA256 inventories establish input identity. Set `java.io.tmpdir` and this library path before starting the JVM. Changing the property after startup is insufficient. No native preload or replacement GDAL availability flag is used.

Consumers must set `java.io.tmpdir` to a fresh, private directory owned by the launching user before JVM startup, and keep it private for the JVM's lifetime. The upstream loader follows filesystem paths in its predictable MD5 extraction cache; this profile does not make extraction into a hostile shared temporary directory safe. For example, start an application with a newly created private directory:

```sh
umask 077
SDK_TMP="$(mktemp -d /tmp/kernel-runtime.XXXXXXXX)"
SDK_JAR="/absolute/path/sdk/kernel-8.30.5-linux-amd64-public-cpu.jar"
SDK_CACHE_ID="$(md5sum < "$SDK_JAR")"
SDK_CACHE_ID="${SDK_CACHE_ID%% *}"
java "-Djava.io.tmpdir=$SDK_TMP" \
  "-Djava.library.path=$SDK_TMP/takkernel/engine/$SDK_CACHE_ID/lib/linux64" \
  -cp "$SDK_JAR:/absolute/path/sdk/third-party/*:/absolute/path/application.jar" \
  your.application.Main
```

```sh
python3 -B takx/sdk-package/build.py --phase qualify \
  --native-proof /data/fresh-kernel-native \
  --providers /data/reviewed-providers.json --source /data/official-atak \
  --output /data/new-sdk-package --java-home /tools/jdk-17 \
  --git /usr/bin/git --patch /usr/bin/patch \
  --nm /usr/bin/nm --readelf /usr/bin/readelf
```

The default `verify` phase checks inputs and actual native symbols without assembly or JVM execution. `package` assembles and verifies the allowlisted artifact but grants no runtime acceptance. `qualify` additionally starts fresh JVMs using only the assembled classpath. It checks actual stock initialization, GDAL availability, native geometry/projection/configuration, encrypted Database2 wrong-key/reopen behavior, GDAL raster data and a real throwing logger. A second package prefix repeats initialization and database/GDAL controls. Exact mapped providers must come from stock extraction; original producer paths, host graphics substitution and shared crypto/SQLite are rejected. A separate missing-resource negative JVM verifies the real loader reports the omission; it terminates after that assertion because intentional failed initialization has no JNI shutdown target.

The same package's fresh JVMs share one owned extraction cache; the relocated package uses another. Each JVM still executes the real loader and verifies every extracted file. Execution uses bounded process groups, a 1 GiB live output limit and a 600-second aggregate command budget. Completed native providers remain read-only. Their historical build facts are preserved, including the exact four license-comment-only changes between the original native producer and its published source profile.

Acceptance covers this component on the validated current host ABI. Native RUNPATHs are preserved; the tested resource order supplies their genuine SONAME providers. Renderer/UI, CommonCommo, host JDBC, credential-store workflows, cross-host ABI portability and a working TAKX client remain unqualified. Reduced GDAL features retain the producer's exclusions for unsupported proprietary codecs.

Offline guards launch no compiler, JVM or native library:

```sh
python3 -B -m unittest discover -s takx/sdk-package -p test_build.py -v
```

### Public runtime resources

The assembler projects all 118 files (6,666,272 source bytes) in the pinned
Kernel engine/shared production `res` and `assets` trees. One upstream Git LFS
pointer is separately bound to its genuine 1,067,496-byte payload; actual runtime
resource bytes total 7,733,636. Supply `--resource-payloads` with an explicit offline
store whose regular filename is the locked SHA-256. The packager makes no network
request and refuses missing or changed payloads and changed pointer identities.
Git blob hashes/sizes remain distinct from materialized payload hashes/sizes. The resource lock binds
Git blobs, SHA-256, file modes, sizes, and JAR destinations. It follows the pinned
`takkernel/gradle/buildconfig.gradle` mapping: `res` becomes `resources`, with the
final filename extension removed; `assets` becomes `assets`, retaining filenames.
Missing, added, changed, nonregular, colliding, or unmaterialized Git LFS
pointer inputs stop assembly.

The desktop catalog indexes 20 raw resources and five PNG drawable byte resources
under `gov.tak.desktop`. IDs are assigned deterministically by the existing
catalog reader; they are not Android or private SDK R values. The reviewed
Resources class family is recompiled beside EngineLibrary using the same qualified
JDK, target release, and frozen classpath. `getIdentifier` and `openRawResource`
provide drawable bytes; this adds no `getDrawable` API. Package-owned raw URI
resolution remains raw-only. A custom context owner must match the catalog owner.
Two values XML files are retained verbatim but unindexed; Android values/style
semantics remain unsupported.

Assets include fonts, styles, certificates, icons, meshes, and the upstream roles
database. Their presence does not qualify each consumer or a renderer. All three
bundled OMT style license files are retained at their original asset destinations,
in addition to the existing package notice inventory. The pinned font directory
contains Arial, Courier, and Segoe MSDF atlases without a font-specific notice;
the official app third-party notice has no matching font attribution. Attribution
coverage for those bytes is unresolved; this change does not assert that every
asset is GPL or establish redistribution rights beyond the supplied notices.

The historical qualified SDK JAR omitted these resources. This source change does
not modify that artifact or claim a new SDK/runtime qualification. Run the bounded
package and runtime controls on a fresh output before publishing a rebuilt SDK.

The qualification recipe also opens every locked asset and catalog entry through
the genuine desktop APIs after stock initialization. It compares all 118 byte
streams, exercises all 15 GL20FP shader lookups through GLSLUtil, repeats these
checks at the second package prefix, and rejects an omitted genuine shader.
These controls require a fresh successful qualification receipt; their source
presence alone grants no runtime acceptance.

### Default database provider read-only options

The assembler applies a narrow pinned patch to the genuine upstream
`DefaultIOProvider` source and replaces its complete existing class family inside
the assembled JAR. Read-only file requests use the existing genuine
`Databases.openDatabase(path, true)` API; zero-option writable open/create and
other provider policies remain unchanged. Source preimage, postimage, patch bytes,
and the complete resulting class inventory are bound in the package manifest.

Database qualification includes native read-only reads, rejected writes, unchanged
rows after writable reopen, and a missing-file request that creates no database.
It repeats these controls through the real provider and MBTiles SPI, including
rejected tile writes and preserved writable updates, at both package prefixes.
The corrected controls passed in fresh JVMs against the exact already assembled
read-only candidate, including both package prefixes and the existing resource,
JNI, database, and logger checks. This was qualification-only reuse after a test
oracle correction, with fresh runtime data and native extraction; it did not
rebuild the artifact or native libraries. The earlier resource-complete SDK
artifact and failed-oracle evidence remain unchanged.
