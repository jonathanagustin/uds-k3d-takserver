# Public-source Kernel native component profile

This opt-in Linux amd64 profile stages the pinned official Kernel **8.30.5** sources and retains all **815** translation units: 483 Core, 159 JNI and 173 Cesium. It uses genuine independently source-built dependencies. It does not substitute a TAKX 5.7/5.8 SDK, build CommonCommo or establish a working client.

The entrypoint completed a fresh local qualification: all 815 translation units compiled, both native libraries linked, and all three strict JNI controls passed in 28.3 minutes. Dependencies were verified and reused, rather than rebuilt. The frozen producer and raw receipt are preserved separately. The published variant adds only license comments to the parent and three Java controls; a separate qualification verified identical native source and command graphs, then freshly compiled and replayed all Java controls against the original fresh native libraries. It does not attribute those native bytes to an edited producer or reuse private predecessor objects.

The lock records 1,396 official Git files, both tinygltf source archives, genuine GLES1 type declarations and two source-file patches: AtomicCounter’s missing platform include and `common.cpp` JNI exception correctness. GLES1 declarations serve the unchanged CPU tessellator; they are not an ES1 renderer. The parent uses complete official source lists and actual Cesium target interfaces, without Conan, vcpkg acquisition or host package fallback. Source archives must already exist in the SHA256-named cache; this profile downloads nothing.

Supply all 14 named proof families in a JSON file: `sqlcipher`, `geos`, `proj`, `assimp`, `las`, `mdb`, `draco`, `spatial`, `gles`, `kml`, `curl`, `kernel_java` are proof-directory strings; `gdal_jni` names `root`, `dependency_root` and `dependency_proof`. `cesium` names `root`, `dependency_root`, `stopped_inventory` and `acquisition_root`; all ancestry paths participate in input/output separation. See `providers.example.json`. The latter preserves the actual failed/stopped GDAL dependency producer→accepted GDAL-JNI chain, rather than fabricating a missing dependency completion receipt.

```sh
python3 -B takx/kernel-native/build.py --phase verify \
  --providers /data/reviewed-providers.json --source /data/official-atak \
  --cache /data/locked-source-cache --output /data/new-verification
```

`--phase prepare` creates a new source layout and private copies of Cesium sources. It changes no source checkout or accepted provider. Each proof is checked against its actual producer source, official input identities, exact source/install/class/header inventories, tools and available runtime evidence. Cesium’s complete stopped ancestor and raw acquisition are rechecked; KML, curl and spatial dependencies are joined to the selected provider identities. Historical consumed Cesium/KML producer variants are accepted only through checked-in exact source manifests and inspectable non-executable source snapshots/diffs; arbitrary frozen recipes and golden private receipt hashes are rejected. Their past tool-path literals are historical data, never executable path defaults. Fresh/resumed dependency facts remain distinct.

The `configure` and `build` phases require explicit JDK 17 and reviewed GCC 14.2, CMake 3.31.6 and Ninja tools via `--java-home`, `--cc`, `--cxx`, `--cmake`, `--ninja`. A fresh output is mandatory: no object copying, incomplete-output reuse or private binary adoption. One compiler job, bounded process groups/logs, 1,800 seconds for Core, 1,200 seconds for JNI and a 3,600-second total budget bound execution. A live 3 GiB output check continues while child processes run, including after stdout closes; it is not a filesystem quota. Providers are verified before and after; successful compilation alone never writes completion metadata.

A full source build uses the same reviewed tool versions and explicit paths:

```sh
python3 -B takx/kernel-native/build.py --phase build \
  --providers /data/reviewed-providers.json --source /data/official-atak \
  --cache /data/locked-source-cache --output /data/new-kernel-native \
  --java-home /tools/jdk-17 --cmake /tools/cmake-3.31.6/bin/cmake \
  --ninja /tools/ninja --cc /usr/bin/gcc --cxx /usr/bin/g++ \
  --nm /usr/bin/nm --readelf /usr/bin/readelf \
  --patch /usr/bin/patch --git /usr/bin/git
```

The final Core link keeps only the two genuine SQLCipher exports needed by JNI (`sqlite3_config`, `sqlite3_errstr`), sharing that instance. Actual SSL/crypto/Expat archive unions must have no intersection with either complete dynamic symbol table, including imports. JNI must contain no second SQLite implementation. The map does not hide unrelated native engine exports or introduce aliases. The runtime validator requires fresh `-Xcheck:jni` processes, real Matrix/Point/WKB/native projection, encrypted Database2 reopen/wrong-key checks, real GDAL data operations and a genuine throwing log-listener control. It binds source GLdispatch/GLES and LAS preloads and audits mapped ELFs; JVM exit 0 is insufficient.

Runtime mode uses explicitly verified native providers. Stock EngineLibrary resource packaging, renderer/UI, network transfer, full CommonCommo and TAKX acceptance remain false. GDAL is the validated reduced 2.4.4 source profile, excluding proprietary MrSID/Kakadu, PRI and PDF where unsupported by its actual producer. Core SQLCipher 4.5.7 / SQLite 3.45.3 is distinct from the optional host JDBC plain SQLite 3.54.1 backend. Historical version security suitability and other target ABIs are not established.

Default tests perform no downloads, compiler, CMake, JVM or native execution:

```sh
python3 -B -m unittest discover -s takx/kernel-native -p test_build.py -v
```
