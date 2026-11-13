# Public-source Kernel component package

The prior recipe's local qualification passed four fresh JVM runs, including package relocation, with zero JNI warnings and all nine native providers loaded from stock extraction. It also passed the missing-resource negative control. The two earlier failed attempts remain preserved separately.

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

### Shader-source lengths

The assembler now stages the pinned official GLES20.java and rebuilds its real
class family with the supported JOGL null IntBuffer shader-source length overload.
The original class family is replaced inside the single Kernel JAR; no duplicate
FQCN prefix or replacement GL API is supplied. OpenGL uses NUL-terminated source
strings, with no Java UTF-16 count passed as a native byte count. Source hashes and
the exact one-call patch are locked; all upstream notices and Kernel identity stay
intact. The existing loader, resource and read-only provider family replacements
remain in place. GLES20Constants is a separate family and is not replaced.

An isolated real JOGL comparison with the unchanged provider demonstrated six
critical-scope warnings using heap lengths and zero with direct or null lengths,
with real shader compile/link and pixel readback. Its heap baseline failed strict
qualification. The genuine GLES20 family then compiled inside a complete 2,697-class derived
view, with GLES20 as the sole changed class. A fresh checked-JNI process registered
a real JOGL context through JOGLGLES and called the production GLES20.glShaderSource
wrapper. Both shaders compiled and linked, two exact red pixels matched, and the
context disposed cleanly with zero JNI or critical-region warnings. Actual class
origins and the loaded native providers matched their pinned inputs.

These component checks cover shader upload through the real wrapper. A newly
assembled SDK bundle, full TAK renderer and complete client still need qualification.
The package qualification above refers to the prior recipe.

## Explicit reduced GDAL composition and OBJ capacity repair

The package recipe repairs the genuine `ObjModelSpi` two-class family. Small valid
OBJ files can estimate index-buffer growth below the eight bytes required for a
vertex/UV index pair. The patch reserves a complete tuple, grows geometrically
and checks integer overflow before allocation. It preserves all other class names.

The optional `--composition declaration.json --composition-sha256 SHA256` selects
`public-cpu-gdal244-kml-v1`. Keep `--providers` pointing at the **original native
producer's providers**. Their strict verifier and equality comparison are unchanged.
The separate composition declaration has exactly these keys:

```json
{
  "schema": 1,
  "profile": "public-cpu-gdal244-kml-v1",
  "finalization_plan": "/data/evidence/finalization-plan.json",
  "finalization_plan_sha256": "<reviewed SHA-256>",
  "finalization_receipt": "/data/evidence/finalization/complete.json",
  "finalization_receipt_sha256": "<reviewed SHA-256>"
}
```

These are caller-declared evidence locations, not prescribed host paths. The
read-only `native-gdal-jni/finalization_validation.py` API independently validates
the specifically supported stopped GNU-inventory execution and its existing
successful finalization. It checks the original source checkpoint, failed receipt,
complete retained evidence, actual ELF products and consumed providers. It writes
nothing and runs no compiler or native/JVM probe. It does not create producer
success. Other failure kinds require their own reviewed validation workflow.

Selection requires the actual reduced closure: `HAVE_SQLITE=no`, 1,073 objects,
absent SQLite-driver registration symbols and both verified GDAL products. Only
this explicit selection removes the automatic `GDAL_SKIP=MBTiles,GPKG` assignment
from the genuine three-class `GdalLibrary` family. Unselected/full-profile source
retains the exact upstream assignment. Caller configuration is preserved by the
reduced variant. No warning filter, error handler or driver deregistration is added.

Qualification runs actual driver-registry absence, real initializer and remaining
MEM/GTiff checks with stock loading and provider-map validation, including relocation.
The package sidecar describes assembly provenance; runtime qualification is recorded
separately in the completion receipt. Neither grants renderer or client acceptance.

The complete six-format regression suite belongs to the separately reviewed
`takx/kernel-regressions` change (#506); this change does not substitute an
unreviewed copy of that directory. Its reviewed source already preserves the
original tetrahedron and repeats the identical analytic geometry assertions on a
compact valid fixture. The retained patch is source-history evidence, not an
additional patch to apply to that updated suite. Retain DTED, MBTiles, GeoPackage, KML, elevation and OBJ,
relocation and both resource omissions as required acceptance controls.

The separate actual candidate04 composition completed all eleven phases, six
formats (including both OBJ fixtures), relocation and both omissions with zero
native/JNI warnings. Its completion receipt SHA-256 is
`f8436e590294cf38683dded113fb250d5301a4146bbae10a278ee361de512a1d`;
the independent audit SHA-256 is
`dc5dddb9e9c15c74e2dcbffde263edb79a6669fd7cb7bba8c94a73c802ff766e`.
Those results validate that composition, not a fresh execution of this public
recipe. Three API-only SLF4J framework lines remained visible. Full SDK, renderer
and client acceptance remain separate.

### Successful and historical composition inputs

An explicit reduced composition may select a normal successful native GDAL/JNI
producer. Its declaration has exactly `schema: 1`, the profile above,
`producer_kind: "successful"`, `producer_receipt`, `producer_receipt_sha256`, and
`producer_recipe_sha256` (SHA-256 of the receipt's `recipe` as sorted compact JSON).
The existing strict public producer replay rechecks current source recipes,
products, inputs, mapped providers and GNU inventory. Selection additionally
requires actual checked-JNI/driver markers, the reduced SQLite-disabled object
closure, registration-symbol absence and ELF dependency checks. A failed producer
cannot use this successful variant.

The existing finalization-plan/receipt declaration is a separate historical
variant: its original execution remains failed, and it never manufactures an
original success. Both variants hash the current transitive validator/producer
source closure into the SDK recipe and keep runtime driver-absence acceptance
pending until actual SDK qualification. These source APIs have offline guard
coverage; neither constitutes a fresh public recipe runtime acceptance.

### Explicit historical native-source binding

A retained native producer can be bound through `--native-source-snapshot DIR`
and `--native-proof-sha256 SHA` together. This does not import or execute code
from the supplied directory. The current SDK consumer pins a known portable
source-bundle manifest and its complete original recipe hash in `inputs.lock.json`;
the invocation separately pins the exact native completion receipt. Unrecognized
bundles, another recipe, missing/changed/extra files, symbolic links and writable
source members or directories are rejected before producer replay.

The reviewed `public-kernel-native-45-v1` bundle has 41 exact Git blobs from
`3780209d7bed4407568cfac902977fecef58727a` and four explicit preimages obtained by
removing only the already reviewed literal GPL notice prefix. Every resulting
byte hash equals the original native recipe. The manifest records each origin;
this is not claimed to be one unchanged historical Git checkout. The receipt and
current source files remain untouched. There is no runtime comment normalization
or general source-hash exception. Existing provider, staged-source, toolchain and
native ELF checks remain mandatory, and the new SDK recipe independently hashes
its current consumer/helper closure.


The portable manifest is distributed as
`native-source-snapshots/public-kernel-native-45-v1.json` (SHA-256
`f8c05d74060ede8407f6cd9fbdf7c9dc0071c4cf232e9dd40409e054f80bb63b`).
Construct its byte-identical evidence bundle offline from a repository that
already contains the pinned Git objects:

```sh
python3 -B takx/sdk-package/materialize_native_source_bundle.py \
  --repository /path/to/uds-takserver --output /fresh/source-bundle
```

The constructor disables Git lazy fetch/network protocols, checks each original
Git blob and exact declared prefix/preimage, then writes all 45 source members,
the frozen recipe JSON and canonical manifest read-only. It never checks out,
imports or executes historical Python. The bundle may be transported through an
offline archive/store if its exact member paths, bytes and read-only permissions
are preserved; the consumer rechecks the known manifest and complete membership.
A construction pass or source-verification pass does not build native products
or grant SDK, renderer or client acceptance. Current public recipe verification
has not passed: the next unresolved guard is the strict baseline provider history
binding, after successful source-bundle admission.
