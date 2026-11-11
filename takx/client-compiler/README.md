# TAKX 5.7 full Client compiler recipe

This source-only, offline recipe compiles all **1,678** official Client Java sources
at revision `0b59a9bb2d0e90dc35c9edfff1c2056daab2b713`, using explicit verified
prerequisite outputs. **This is a compiler checkpoint requiring separately supplied
verified artifacts, not an end-to-end publicly reproducible SDK/client build.**
It emits a fresh Client class directory and the real
EventBus annotation processor's `gov/takx/core/event/ClientEventIndex.java`.
No downloaded JARs, compiled classes, official source snapshots, or native
binaries are shipped here. Nothing is acquired automatically. No Gradle task,
native build, native library loading, GUI, client execution or publication runs.

The qualified local compiler receipt is SHA-256
`fa8a8f2b4ad2fab40ba57f7a8f1993962da5a0c122080199fefbf4cdfe7041d5`:
1,678 sources, zero compiler errors, 2,815 classes and one processor-generated
source. Its interrupted predecessor's Client output is **not** a prerequisite.
The pinned receipt and original helpers are retained as input evidence; this
recipe never executes those helpers or their embedded historical paths.

The portable recipe was also run against that checkpoint in fresh output. It
returned exit 0 and produced identical hashes for all 2,815 classes and the
generated source. Its receipt is SHA-256
`bc9a5fdba7c837fdaa1acebc3f8fdba831293a8ca790a012432ca35bf73d9c52`.

## Explicit inputs and offline use

Copy `bindings.example.json` outside the repository and replace every value with
an absolute directory holding the named input family. The names are stable
logical identifiers; they impose no directory layout. An input family can live
anywhere, including on a read-only mounted evidence volume. The complete mapping
is required: there are no workspace path defaults, discovery, cache fallbacks,
network fetches or unverified dependency substitutions.

```sh
python3 takx/client-compiler/build.py --bindings /absolute/path/bindings.json --check-inputs
python3 takx/client-compiler/build.py --bindings /absolute/path/bindings.json --output /absolute/path/fresh-client-output
```

The output parent must already exist; the output directory must not exist and
must not overlap any input root. `--check-inputs` is read-only and does not start
Java. Compilation requires Python 3.9+ on Linux and the explicitly bound pinned
Temurin 17.0.21+9 JDK. The lock binds `java`, `javac`, JDK `release` and `lib/modules`;
it is an executable/JDK-module identity check, not a full operating-system or JDK
shared-library reproducibility claim. Supply the same qualified JDK distribution.

`inputs.lock.json` pins the actual compiler and processor path order, all consumed
source files, every dependency JAR digest, proof files, complete prerequisite
class inventories, source-tree membership, and expected output class names.
Verification runs before compilation and after successful compilation. The
original Client source tree must contain exactly its pinned Java source set.
Exactly two reviewed WorldWind consumer import postimages are compiled from the
WorldWind proof family; their original upstream sources are also checked.

The prerequisite class families are:

| Family | Complete class count | Meaning |
| --- | ---: | --- |
| Bootstrap preferences | 2 | Complete qualified preferences compiler output |
| Bootstrap | 15 | Complete qualified Bootstrap compiler output |
| ProcessManager | 5 | Complete qualified ProcessManager compiler output |
| Platform | 2,098 | Complete Platform output including real processors |
| Platform aspects | 8 | Four actual `.aj` inputs; `aop/aop.xml` also pinned |
| Kernel project profile | 15 | Explicit project source overlay |
| Frozen context profile | 45 | Frozen `a8a4fda8…` production context classes |
| Texture profile | 4 | Compile-only texture/context family overlay |

The coordinator's complete Platform prerequisite includes **17** processor-generated
Java sources plus XJC/schema and Java-template generation, all checked through
its qualified source inventories. Platform templates deliberately identify public
component versions; the coordinator's documentation-only dependency tables are
not claimed to reproduce Gradle's tables. This recipe consumes the complete
verified outputs; it does not rebuild or accept partial Platform classes.

## Actual dependency identities

The actual SDK is Kernel **8.30.5** plus the explicit Kernel, Texture, frozen
Context and WorldWind project profiles, and CommonCommo **1.17.2**. They do not
become the upstream private Kernel **8.57.11** or CommonCommo **1.20.0** by passing
javac. The exact selected public JAR identities and classpath order live in the
lock, alongside the pinned dependency-selection evidence. In particular,
annotations 26.1.0 replaces 13.0, and mil-sym 2.1.5 uses geodesy 1.1.3 and jsvg
1.6.1 (instead of the direct Client jsvg 1.4.0 declaration). Public-source UI
candidates and NASA WorldWind interop are explicit project artifacts.

The frozen context checkpoint is exactly **eight source files / 45 classes**,
receipt `a8a4fda8738cad8483986b9faa66f0f871a015947b480af8d66e50ce1851649b`.
Its eight immutable snapshot sources and output manifest are independently bound.
The current mutable context profile has advanced to 15 sources and is not an
input to, or a claimed producer of, this checkpoint. A portable public source
recipe that recreates this frozen context artifact remains required for an
end-to-end source build. Do not substitute classes built from the mutable profile.

No old SDK JAR is silently selected over the reviewed Client selection. The
original `classpath.json`, selection departure evidence and qualified coordinator
result are digest-bound inputs. Artifact basenames and SHA-256 values are
inspectable in `files`; the `classpath` and `processorpath` arrays define the
actual ordered dependency closure. A matching filename alone is insufficient.

## Closure still required for an end-to-end source build

The consumer lock intentionally binds supplied artifacts instead of claiming to
recreate their producers. A fresh machine still needs the exact 129 dependency
JARs (the compiler classpath has 137 entries including eight class directories),
the pinned JDK, the official source tree plus the two staged import postimages,
the complete prerequisite class families above, and their pinned proof files.
No binary input is included in this repository.

Public producer recipes must additionally recreate and qualify the frozen
eight-source Context artifact, the four-class Texture compile-only artifact,
the exact Kernel SDK candidate and Kernel15 overlay, WorldWind interop plus its
two postimages, the original UI/Wizard candidates, CommonCommo JAR, and the
selected public/Mil-sym/GIS dependency JAR closure. Some component recipes exist
elsewhere in this repository; their existence alone does not prove that they
recreate every exact digest in this checkpoint. The Platform/Bootstrap/
ProcessManager producer still needs a portable lock and recipe for XJC,
Java templates, AutoValue/EventBus processing and four-aspect compilation.
The coordinator evidence verifies the supplied output but its historical
workspace helper is not a portable producer. Full source-to-artifact regeneration,
then the Gradle and runtime gates below, is the remaining reproducibility work.

## Bounds and acceptance

The compiler uses `--release 17`, UTF-8, `-implicit:none`, an empty source path,
768 MiB heap and `ActiveProcessorCount=2`. The owned process group has a 240-second
wall deadline, within an 1,800-second aggregate deadline; output monitoring
checks a 2 GiB free disk floor, 15 MiB aggregate output cap and 1 MiB compiler log
cap. Monitoring is sampled while the compiler runs and quota violations terminate
the process group; a filesystem quota is needed for a hard instantaneous byte
ceiling. The receipt-inclusive cap is checked before publishing success. Inputs
are outside that new-output cap. Java option injection variables and loader-path
injection variables are removed from the child environment.

Success requires normal compiler exit, zero recognized Java errors, the exact
2,815 expected class names, precisely one real generated EventBus index, unchanged
inputs and complete prerequisite class sets. The receipt records fresh output
hashes rather than asserting byte-for-byte reproducibility from matching names.
Failed output is retained for inspection and must never be reused as a prerequisite.
The compiler/annotation processors are trusted digest-pinned inputs; this helper
does not provide a network sandbox. Run it in an offline sandbox if network
isolation is required. CPU and wall controls are compiler controls only.

## Remaining Gradle and runtime gates

The pinned official build files establish the following unfulfilled gates:

1. **Gradle resolution and generation.** Root `build.gradle` uses build-support
   10.1.0, JBoss modules plugin 3.5.0 and checker-processor 2.0.4; Platform uses
   FreeFair AspectJ 9.1.0. Complete plugin/transitive resolution, checker
   processing, test configuration, manifests and generated dependency tables
   require separate validation. The wrapper properties select Gradle 9.2.1-all,
   while the root wrapper task configures 9.2; this compiler does not resolve that
   discrepancy or claim a successful Gradle build.
2. **Aspect compilation and weaving.** `Platform/build.gradle` re-enables javac,
   makes `compileAspectj` depend on it, supplies main output for type resolution,
   and explicitly empties `inpath` and `aspectpath`: compile aspects only, no
   compile-time weaving. It emits `aop/aop.xml` with `-XhasMember` and
   `-Xlint:ignore`. Eight aspect classes prove compilation, not load-time weaving.
   `gradle/standardTestSetup.gradle` uses a Bootstrap Java agent; agent loading,
   module visibility, weaving behavior and integration tests remain untested.
3. **Resources, JARs and modules.** `gradle/artifactTasks.gradle` handles load JARs;
   root build setup configures manifests. Client/Platform source resources,
   service registrations, generated aspect XML placement and Bootstrap agent
   manifest need assembled-JAR inspection. `gradle/binCreator.gradle` uses
   `generateJbossModules`, custom module token replacement, `buildAllLibsModule`
   and `copyModulesToBin`; javac's flat classpath proves no module graph or
   packaged resource correctness.
4. **Distribution and native closure.** `bin-creator`/`deployment` and `createBin`
   collect deployment resources, TAK assets, modules, load/boot/lib artifacts and
   platform native classifiers for JOGL, GlueGen, JOCL and FFmpeg. Their complete
   distribution, launch scripts, native symbols and actual Linux launch must be
   validated separately. The accepted baseline JNI lacks the newer texture
   symbols needed by the compile-only feature overlay. No new feature runtime
   or private SDK equivalence is accepted by this compiler recipe.

These are next gates, not failures masked by a synthetic Gradle success.

## Mission-package admission variant

The optional [mission profile](../mission-package/README.md) exports checked
actual source postimages without changing the frozen baseline lock. To consume
it, supply all three arguments together:

```sh
python3 takx/client-compiler/build.py --bindings /verified/client-bindings.json \
  --mission-admission-projection /verified/source-projection \
  --mission-platform-proof /verified/full-platform-proof \
  --mission-platform-receipt-sha256 REVIEWED_RECEIPT_SHA256 \
  --output /fresh/client-proof
```

The genuine full Platform producer/verifier is included alongside this recipe;
see [PLATFORM.md](PLATFORM.md). An old Platform artifact or small class overlay
cannot satisfy the gate. The old Platform CP entry is replaced in-place and
only the checked Client postimage is substituted. Input/source-argument and
profile/artifact postchecks remain mandatory. `--check-inputs` performs no compile.
A sparse checkout must also materialize the genuine locked
`takx/native-commoncommo/runner.py`; the current dry-check does not yet test this
local helper's availability. The first local attempt stopped before javac for
that checkout omission; its output was preserved separately.

The variant retains the 15 MiB logical output cap and reserves/caps 32 MiB of
physical allocation above the 2 GiB floor, including the receipt. Heap is 768 MiB,
two active processors, command deadline 240 seconds. Actual compiler acceptance
remains distinct from native execution, application/CDI/UI and transfer success.
