# Texture qualification checkpoint

The frozen source profile is commit
`ec83eaa0eeed3b37caf57d3cfba0e9850685655b`. Its patch and source lock remain
unchanged by this documentation update:

| Input | SHA-256 |
| --- | --- |
| `texture-fill.patch` | `058227ac202f037ec65d4eb1ca8eff612e7326695c45336c320e5a1081013c80` |
| `source.lock.json` | `7497d59b0b0e4c675387660fc536b2ba547e7410c9f8f018edb5b72a662f044e` |

The following are existing local evidence receipts, identified by digest. They
are not distributed binaries or a portable end-to-end SDK build attestation.
No new build or runtime control was executed for this documentation update.

| Evidence receipt | SHA-256 |
| --- | --- |
| Native03 `render-context-combined-variant-03/complete.json` | `f877cff977425118d9898481cf20820e39c9877aad1da537e37ba9e02106bd52` |
| CPU04 `render-context-cpu-runtime-attempt-04/runtime-receipt.json` | `a27631b5a7ddf7492ce0413e168415a475f149f173c2a3fb936beb9778a64b7c` |
| CPU04 Texture stdout | `43d7c90850dd110e3c0cde51373123f92c1b4f2ecd5faa98f9d913335e0ff9ad` |

Native03 compiled the **108-object composed affected closure** and relinked Core
and JNI using the reviewed Texture, Scene, context and other project inputs.
It retained all 1,326 baseline Java exports, resolved changed-header descriptors,
and passed its backend symbol/privacy and single-SQLite-owner static audits.
It verified original baseline inputs remained unchanged. This is actual composed
closure evidence, not a newly built standalone Texture profile. The earlier
78-object standalone dependency-log estimate remains historical; a standalone
build requires a fresh dependency scan and its own qualification.

CPU04 used those composed native providers and the explicit Java class origins.
All five CPU phases exited normally with zero JNI warnings under `-Xcheck:jni`:
baseline basics, database, logger, Texture and Scene. The Texture phase executed
`nativeClass`, `create`, `uri`, `integer` and `rotation`, checking URI, ARGB,
per-axis repeat/stretch, dimensions, rotation and absolute anchoring values.
It cloned the native style, checked actual class dispatch, disposed the original,
then verified and disposed the independently owned clone. Its success token is
`PASS_TEXTURE_FIVE_NATIVE_CPU_METHODS_AND_CLONE`.

The other **three new CPU JNI bridges belong to Scene**, with positive native
store/query/visibility checks. They are separate component evidence, not three
additional Texture methods. No context GPU native method was exercised. A URI
getter returning the supplied string does not prove image decoding or loading.

The executed Texture candidate was narrower than the checked-in
`TextureStyleControl.java`: it did not establish composite equality, OGR parser
or serialization round-trips. `builder-control.cpp` still has syntax-only
qualification. URI decoding, asynchronous loader/atlas completion and failure,
refresh scheduling, nested styles/siblings/edit overlays, the complete batch
builder/renderer lifecycle, atlas eviction/context recovery and a TAKX drawable
remain unqualified. The existing focused shader pixel control is separate from
these linked CPU checks. Perspective/horizon, surface pixel density, global
wrap/poles and performance gates also remain open.

Native03 used one compiler job, 45-second object and 120-second link deadlines,
a 600-second aggregate deadline and 112 MiB owned allocated-output cap. CPU04
used 120 seconds per phase, a 256 MiB Java heap, two active processors, a 16 MiB
runtime allocation cap and a 2 MiB phase-log cap. Both used the coordinated
400 MiB allocated phase budget and 2 GiB free disk floor. Native03 recorded
359,546,880 phase bytes before its receipt; CPU04 recorded 366,702,592 aggregate
allocated bytes and 2,197,438,464 free bytes after its run. These are compiler
and local CPU-control bounds, not renderer performance or production guarantees.

Full renderer/context/GPU behavior, assembled SDK/client distribution, private
SDK equivalence and production client readiness are not accepted by these
receipts. No ordinary server build, package or CI workflow enables this feature.
