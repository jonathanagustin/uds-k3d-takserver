# Public Kernel engine, port and annotation compilation

This opt-in recipe compiles the pinned public desktop **engine, port and
annotation** Java profile from official `TAK-Product-Center/atak-civ` revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`, together with the repository's desktop
compatibility adapters. It produces frozen sources, compiler output and a
verifiable input/output manifest. It does not package TAKX, build or load JNI,
start a renderer or claim full client compatibility. The default scope does not compile the separate `takkernel/shared` module.
The explicit `--scope engine-shared` option adds all of its desktop sources;
neither scope assembles a complete Kernel SDK. The
[client feasibility checkpoint](../CLIENT-CHECKPOINT.md) distinguishes these
module boundaries from the earlier source-import inventories.

**The default profile uses patched dependency versions.** The explicit
`--profile baseline` option retains the historical inputs with known advisories.
See the [dependency assessment and recorded scan](DEPENDENCIES.md). Neither
classpath is a runtime dependency recommendation. The recipe disables
annotation processing and does not run the compiled code or load JNI.

## Exact scope

[inputs.lock.json](inputs.lock.json) records the official dependency URLs and
hashes, source selection and GIS class fingerprints. All Java files in these
pinned desktop roots are included; individual source files are not filtered out:

| Source root | Java files |
| --- | ---: |
| Annotation `src/main/java` | 6 |
| Port `src/main/java` | 57 |
| Port `src/jre/java` | 20 |
| Engine `src/main/java` | 848 |
| Engine `src/jre/java` | 14 |
| **Upstream total** | **945** |

The recipe exports these files from Git at the exact commit, checks their complete
path/hash inventory, and rejects changed consumed source trees. All 862 engine
files retain their original bytes. The existing reviewed, hash-checked
[unused-import patch](../patches/0001-kernel-remove-unused-colorfilter-import.patch)
changes only `ColorBlendModeMarshal.java`; the other 944 upstream files remain
byte-for-byte identical. No SDK stub or replacement upstream method is supplied.
The real adapters in `takx/compat/src/main/java` must be tracked, unmodified
regular files matching the recorded repository commit. Untracked Java files
(including ignored files), modified sources and symlinks are rejected; unrelated
worktree edits are allowed. Verified committed bytes are frozen directly, and
their complete path/hash inventory is recorded separately from upstream sources.

The classpath contains exactly 25 inputs:

- 23 public JARs match their locked byte hashes. The default `patched` profile
  retains 17 original JARs and replaces six with separately pinned versions.
  The explicit `baseline` profile retains all 23 original JARs for historical
  comparison. URLs point to Maven Central or the official JogAmp repository.
  These are compiler inputs, not a complete runtime dependency closure.
- Two GIS Java JARs come from the checked-in
  [official-source GIS recipe](../gis-java/README.md). Its current source lock,
  recipe/probe identity, completed output inventory and source counts are verified.
  The JARs must contain exactly the original probe's 60 GDAL and 47 jassimp class
  entries, with every class byte hash unchanged. Additional classes are rejected.

Rebuilt GIS JAR hashes can differ from the original probe due to ZIP timestamps,
manifest and license/notice entries. The result records each **actual whole-JAR
hash**, its original baseline hash, whether those match, and the 107 identical
class entries. The baseline has **23 original JARs plus two source-rebuilt,
class-identical JARs**. The patched profile has **17 original JARs, six upgraded
JARs and the same two rebuilt GIS JARs**. Neither profile claims that all 25
original container hashes remain unchanged.
Both artifact paths and the rebuilt source recipe stay under caller control;
there is no dependency on this investigation's local cache paths.

## Optional shared module

`--scope engine-shared` retains the entire default profile and adds all 212 main
and 19 JRE Java sources from `takkernel/shared`. Its combined locked inventory has
1,176 upstream files (1,175 unchanged, with the same single unused-import patch)
and 59 desktop adapters. All 231 shared files retain their pinned bytes. The
source manifest and result explicitly record the scope and shared-source count.
The default `--scope engine` remains the original engine/port/annotation profile.

The shared scope has 33 public JARs plus the same two source-built GIS JARs.
Ten additional public inputs come from the pinned shared Gradle declarations
and POM dependency chain: Jackson's three modules, two military-symbol renderer
artifacts and five renderer transitives. The patched profile uses Jackson
`databind`/`core` 2.23.0 and `annotations` 2.23; the historical baseline retains
2.13.1. The [shared advisory receipt](shared-advisories.json) covers all 33 direct
classpath coordinates; see [limits and dependency provenance](DEPENDENCIES.md).
The combined baseline has 33 locked historical public JARs; patched retains 24
and upgrades nine. These counts do not mean 33 inputs existed in the original
25-JAR engine investigation. The separate GIS container/class equivalence rules
remain unchanged.

A fresh patched shared compile produced 2,697 class files from all 1,235 sources,
with zero errors and four warnings. The earlier 274-diagnostic incomplete
classpath probe and the later one-error Paint API probe remain failed historical
evidence; their partial outputs are not dependencies of this recipe.

## Run

Use Python 3.9+, Git, `patch`, and JDK 17. The GIS source recipe additionally needs
its documented SWIG 4.3.0 tool/resources. Tools are trusted local prerequisites;
this recipe does not install them. Initialize the existing official gitlink or
provide another clean checkout at the exact revision, and build the GIS Java
outputs with `takx/gis-java/build.py` first.

```sh
GIT_LFS_SKIP_SMUDGE=1 git submodule update --init upstream/atak-civ
export JAVA_HOME=/path/to/jdk-17

python3 takx/kernel-java/build.py \
  --source upstream/atak-civ \
  --classpath-dir /absolute/path/to/public-jar-cache \
  --gis-build /absolute/path/to/completed-gis-java-build \
  --output /absolute/path/to/new-kernel-java-proof \
  --fetch-dependencies
```

Add `--scope engine-shared` to the command above to compile the shared module.
The default is `--scope engine --profile patched`. Use `--profile baseline` only to reproduce
the historical compilation comparison, with a separate new output directory.
Each receipt names its selected profile and records actual input hashes.

`--fetch-dependencies` permits downloading only missing public JARs from the
locked URLs, with exact size and SHA256 checks. Existing mismatched files fail;
they are never replaced. Omit the flag for offline use. The recipe does not fetch
upstream Git objects or GIS source archives. It respects the normal proxy/TLS
configuration for permitted public downloads.

Output must be a new directory outside the checkout. Existing or partial outputs
are refused; select a fresh name. Inputs are copied into the proof directory, so
later changes to the caller's source or dependency caches cannot change the
recorded compilation. Paths containing spaces are supported; classpath separators
and line breaks are refused in output paths.

Compilation is bounded to 768 MiB, two active JVM processors and 180 seconds,
using Java 11 compatibility. Annotation processing and implicit source lookup are
disabled; every compiled source is an explicit frozen input. No Maven/Gradle
build, native toolchain or client application runs.

## Evidence and tests

The output contains:

- `inputs.json`: every actual compiled source and classpath hash, upstream
  original hashes, patch, toolchain, recipe and GIS receipt identities.
- `stage/`, `classpath/`, `sources.args`, `classpath.txt` and `command.json`:
  frozen inputs and the exact compiler command.
- `classes/` and `class-hashes.json`: compiler outputs and per-class hashes.
- `stdout.log`, `stderr.log` and `result.json`: diagnostics, source counts and
  explicit `native_or_client_acceptance: false`.

All frozen source and dependency hashes are rechecked after compilation. A
successful compiler exit is required; a timed-out or failed attempt leaves its
logs for diagnosis. Source/output hashes are local integrity evidence, not a
signed attestation or a promise of bit-reproducible outputs across toolchains.

Run offline guard tests without downloading or compiling the engine:

```sh
python3 -B -m unittest discover -s takx/kernel-java -p 'test_build.py' -v
```

A successful output is directly accepted by the focused
[graphics/Unix/unchanged VSI checks](../compat/FINAL-APIS.md):

```sh
python3 takx/compat/test-final-apis.py \
  --source-dir /path/to/pinned-api-reference-files \
  --kernel-proof /absolute/path/to/new-kernel-java-proof
```

Those focused checks still do not establish native GIS/GL/Kernel linkage,
rendering/recovery, TAKX packaging/resources, enrollment, CoT exchange or complete
database/native interoperation. Both official TAKX client candidates still need
full application and runtime acceptance.
