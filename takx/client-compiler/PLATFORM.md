# Full Platform producer for mission-package admission

The baseline Client recipe takes a frozen, complete Platform class directory as
an input. Patching three Platform sources does not change those classes. The
mission-admission Client profile must therefore consume a newly compiled **whole
Platform** artifact, replacing the old classpath element entirely.

`platform_producer.py` provides that producer and its shared consumer gate,
`verify_platform_proof(profile_file, profile_sha256, proof_root, receipt_sha256)`.
It does not create a two-class overlay, rename SDK versions or alter the baseline
Client lock or earlier proof directories.

## Exact source and compiler scope

`platform-inputs.lock.json` binds the actual Platform prerequisite set used by the
accepted public-source Client compiler:

- All 1,815 Platform compiler inputs: 1,741 official TAKX 5.7 sources, 70 frozen
  XJC sources, three frozen version templates, and the existing reviewed
  WorldWind import variant.
- Six complete class directories and 129 JARs, with a separate 129-JAR processor
  path. The previous full Platform artifact is absent from this javac classpath.
- The actual AutoValue and EventBus annotation processors and qualified JDK 17.
  Seventeen generated source names are expected from a fresh processor run.
- The baseline 2,098 class names plus the one mission-profile production nested
  class, `ZipReader$BoundedEntryStream`.

The v2 compiler replaces only `Platform/.../PackageReader.java`,
`Platform/.../ZipReader.java` and `Platform/.../PackageImporter.java` with their exact mission-profile postimages. The
fourth profile source, Client's `DataPackageManager.java`, belongs to the separate
whole Client compilation. Both original source trees remain unchanged.

The old Platform substage succeeded inside a later interrupted compiler probe.
Its overall old result is not relabeled as a new producer success. The new
producer runs all Platform sources into an empty directory and writes its own
complete class, generated-source, profile and input-postcheck inventories.

This is compilation only. Frozen XJC/templates, preference/bootstrap/process,
Kernel, Texture, Context, WorldWind and CommonCommo prerequisites are inputs,
not newly generated or runtime-qualified here. The original closure emitted
annotation/unused-processor-option warnings; new diagnostics are retained and
counted, without a zero-warning claim. Full Gradle, aspect weaving, Client
runtime, JNI and private SDK equivalence remain separate gates.

## Verify inputs without compiling

Use the exact root aliases from `platform-inputs.lock.json`, a frozen profile,
and its independently verified source projection receipt:

```sh
python -B takx/client-compiler/platform_producer.py \
  --bindings /absolute/producer-bindings.json \
  --profile /absolute/mission/admission-profile.json \
  --profile-sha256 REVIEWED_PROFILE_SHA256 \
  --projection /absolute/mission-source-projection \
  --projection-sha256 REVIEWED_PROJECTION_RECEIPT_SHA256 \
  --check-inputs
```

The projection layout is `source/{Platform|Client}/...` plus `projection.json`.
All four checked postimages and their profile/patch identity must match. The
producer verifies original preimages, full source-directory membership, every
compiler dependency and exact frozen prerequisite class sets.

Omit `--check-inputs` and add `--output /fresh/disjoint/path` only after reviewing
the compiler command and resources. The producer reserves 24 MiB inclusive of
classes, generated sources, diagnostics and a 2 MiB final receipt. It maintains
the 2 GiB physical free floor, uses a 768 MiB Java heap/two active processors and
stops after 240 seconds or bounded diagnostics. There are no downloads, implicit
source compilation, application launches or native SDK loads.

## Consumer contract

The new `complete.json` must bind the profile ID/SHA, patch SHA, official source
revision, all three Platform postimages, all 1,815 source identities, the producer
recipe/lock, all actual classes and generated sources, and successful input
postchecks. The consumer checks the receipt's independently reviewed SHA and
rehashes the entire new class directory before replacing the old Platform
classpath entry. Missing, stale, failed or mismatched producer metadata fails
before Client javac; it never falls back to the frozen old artifact.

Offline guards run without a compiler:

```sh
python -B -m unittest discover -s takx/client-compiler -p test_platform_producer.py
```

Those guards test admission failures, not mission-package behavior. The patched
reader conformance run and a whole Client compile are separate, explicit proofs.
