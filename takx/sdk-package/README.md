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
