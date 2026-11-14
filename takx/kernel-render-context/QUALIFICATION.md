# Render-context project variant qualification

Status: experimental source profile. Native linking/static audits and five CPU
Java Native Interface (JNI) controls have passed locally. Headed OpenGL lifecycle
remains unqualified.
The actual upstream identity remains Kernel 8.30.5 at official commit
9f6893dd657feacc35ec5de03dad721c2e44170e.

## Bounded worker retirement regression

The pinned `ControlWorkerImpl::doAnyWork` returns `TE_TimedOut` after consuming
its requested work budget, even when every executed Work completed successfully.
The retirement wrapper already closes submissions and cancels remaining queued
Work after that bounded drain. Propagating its budget status then incorrectly
throws from JNI and prevents the remaining context cleanup. Normalize only that
expected drain status alongside the existing Done/Interrupted cases; cancellation
and interrupt errors continue to propagate.

The CPU control compiled the exact extracted production wrapper with eleven
complete official native units and their verified header closure, without
function garbage collection or substitute native dependencies. Before the fix it
exited 18 with `retirement=14 expected=0`, after confirming one completed Work,
one cancelled Work, rejected foreign/stale submissions and preserved genuine
delegate errors. The first failed executable and its output remain separate.
The corrected control exits normally with `retirement=0 expected=0` and the same
completion/cancellation/error controls. Its runnable entrypoint and exact-source
checks are documented in README. The full 57-path source projection also passes.
The final control receipt is
`19d9e13d533654be7f9d3c074ab6476c895787e0fecae0f8a5493d14f83279ab`;
it binds 29 official source/header files, the producer/contracts, compiler,
27 actual commands and all compiled outputs.

This is a CPU regression result only. It has not rerun the failed headed
lifecycle, rebuilt Core/JNI, qualified the later unpublished Java callback
candidate, or established renderer/context-recreation acceptance. The prior
graphics failure and every headed gate below remain open.

The patch targets TAKX's actual stop/release, current replacement context,
setRenderContext, configure, start sequence. This is a project-defined lifecycle;
it is not evidence that the unavailable newer private Kernel implementation was
reconstructed. Legacy GLMapSurface views retain their existing lifecycle.

## Reproducing native qualification is a separate gate

Freeze final feature patches and all pre/postimages. Compose TextureFillStyle
separately. Recompute the union of their full reverse dependency closures from
recorded Ninja dependencies. Rebuild every affected object in new private output;
never overwrite accepted objects or mix objects compiled against changed headers.
The checked-in reverse-dependency inventory preserves the earlier conservative
107-object plan. The complete dependency-only scan discovered one additional
consumer of the final GLMapView JNI header, producing an actual 108-object union.
Neither inventory is a portable rebuild command. The full graph and all final
generated headers must be rechecked for any new toolchain or source composition.
This profile introduces no consolidated native-builder flag.

## Local native and CPU evidence

Native03 receipt SHA-256:
`f877cff977425118d9898481cf20820e39c9877aad1da537e37ba9e02106bd52`.
It binds 108 fresh objects with immediate per-object records and two genuine
shared-library links. All 1,326 baseline Java exports were retained, all 11 new
implementations and changed descriptors resolved, and exact dependencies,
RUNPATHs, no-TEXTREL, complete SSL/crypto/Expat dynamic-symbol privacy and a single
Core SQLCipher body owner passed. Full compressed tool output and input rehashes
were preserved. The inherited 142 unresolved baseline descriptor requirements
remain recorded; this is not complete SDK JNI coverage.

CPU04 receipt SHA-256:
`a27631b5a7ddf7492ce0413e168415a475f149f173c2a3fb936beb9778a64b7c`.
The basic, Database2/GDAL, throwing-logger, Texture ownership and Scene JNI modes
all passed in actual fresh JVM processes with zero strict JNI warnings and normal
exit. CPU Texture ownership does not establish textured rendering. No headed
execution or context GPU native method ran. These local receipts are evidence
identities, not inputs adopted by the portable source-preparation recipe.

## Current source and incremental runtime evidence

The current 57-path recipe incorporates seven later source updates: checked text
callbacks and exception propagation, atlas binding restoration, and guards for
optional terrain attributes optimized out of a shader. Cached official source,
all five patch stages, and the seven actual build-source images were rechecked.
The earlier native03 and CPU04 receipts describe their original composition;
they do not by themselves qualify these later changes.

The incremental native10 build compiled one terrain source file and linked new
Core and JNI libraries over the preserved native09 atlas, native08 text callbacks
and original context composition. Its receipt is
`d3eba81bda9efb94076c7f2cf492576a3600efbed9fdf40db493fd535be9900c`;
the separate static review is
`56fcd2642b32cb4a45cb53da488aa0386fcf6a26429343b3be290bee227a8b94`.
The review verified all 26 output files, 16,304 input pins, 119 generated headers,
the actual 483 Core and 159 JNI link objects, retained exports, backend privacy
and single SQLCipher ownership. These are local build identities, not a portable
builder or a new complete software development kit (SDK).

Fresh native10 CPU callback controls exited normally with zero strict JNI
warnings; receipt
`d89e5ec4ed5189a7cb37fbf1977cb6af46ebe02329295601938b18e1beca3585`.
Font controls also exited normally, but retained 418 known Java Development Kit
(JDK) font diagnostics and no project or unknown diagnostics; receipt
`3ca80433f96f93a24c33d2b8b15651f7acbbb16412de109b49caefb26348635e`.
That font result is a scoped result, not globally clean `-Xcheck:jni` execution.

The first native10 headed attempt is preserved as failed:
`604545af5ff79c90147b9a0a53a666f45dc4884fd68f669db7bc233ecd6d77d9`.
Both initial views rendered without the prior terrain OpenGL error and produced
matching cold/warm glyph pixels. The attempt then failed the moved-disposal-thread
assertion; its complete logs also retain window-event lock timeouts. It did not
complete the recreation, worker-retirement or terminal-collection checks below.
The actual callback routing and capture overhead remain under investigation.
No full lifecycle, global strictness or production rendering claim follows.

## Additional compile-only evidence

Fresh Context73 Client replay receipt SHA-256:
`23bf081b46a210ceffede8dcc7032148e363352c072dafc139bba7e7e1b25cb6`.
The actual 5.7 Client compiled 1,678 sources into 2,815 classes with zero errors
using the final 73-class Context overlay. Existing Platform and prerequisites
were reused; this was not a whole-project rebuild or runtime execution.

Headed helper/probe compile receipt SHA-256:
`adb324729ef2133e5e83b714f282dfd3a96583e94071de5e6f030b47d6413be1`.
Three Java sources produced six classes; the native diagnostic helper has four
JNI exports and links against the genuine variant Core. Neither the helper nor
the libraries were loaded, and no graphical context or GPU control ran. The new
test-only integration is a separate source checkpoint, not graphical acceptance.

## Required genuine headed checks

Use real JOGL/Gluegen 2.5 with matching official native classifiers, JDK17,
DISPLAY=:0, and the existing managed Xorg authentication. Bind classifier source,
published checksum/signature availability, local hashes, all loaded providers,
class origins and actual compiler commands. No synthetic RenderContext can count
as a GL qualification. Do not alter accepted prefixes or use version aliases.

1. Before canvas realization create the real JOGLRenderContext, Globe and
   GLMapView through the actual Client-selected com RenderContext overload.
   No current or bootstrap GL context is permitted during construction. Then
   realize the canvas and require the actual registered control. Render
   and verify actual pixels, including native batch geometry and textured polygons
   when composed with the TextureFillStyle patch.
2. Retain Java GLText and Shader references and native resource/thread workers.
   Queue real owned work. Stop and release while the old GL context is current;
   verify its work drains and resources are deleted in that context. Old workers
   must return TE_Canceled for newly submitted tasks.
3. Destroy/recreate the actual JOGL context, rebind the same view, configure/start,
   and verify pixels and retained text/shader recreation. Repeatedly cycle. Check
   old drawable callback envelopes cannot invoke GPU work in a replacement context.
4. Move the same context between two real GL threads for initialization/rendering
   and disposal; verify scoped cleanup reaches resources cached on the former
   thread. The correct context must be current during every cleanup.
5. Keep a second live view/context rendering throughout the first view's cycles.
   Verify its resources, work, pixels and shader identities remain valid.
6. Dispose the first view terminally while current. Explicitly invoke every
   retained public GLText draw/batch family and Shader.get on its retired binding;
   require safe exceptions before native GPU access. Rebinding a disposed view
   must fail. Keep the second view functional.
7. Wrong-thread, un-released, shared-context, reentrant release and pending-work
   transitions must fail explicitly. Failure during recreation is terminal for
   rendering; cleanup remains possible on the new current context.

Require zero -Xcheck:jni warnings, bounded logs/deadlines/disk, actual mapped ELF
hashes before/after, and whole-process normal shutdown. Preserve the first failed
attempt. Do not infer SDK packaging, stock EngineLibrary resources, all-platform
ABI, renderer completeness or full client readiness from these controls.

## Additional source and compile-only evidence

The Java vertical slice compiles against the frozen 1235-source Kernel classes
and its actual dependency classpath. A state-only unit test currently passes 40
assertions. It is explicitly a test double and supplies no GL/runtime evidence.
Changed native TUs pass -fsyntax-only with recorded compiler flags; the first
namespace-qualification diagnostic is preserved separately. No object or shared
library was produced by those syntax checks; the later native03 qualification
above is a separate actual object/link proof.

Global GLText invalidation preserves its global intent by queuing GPU cleanup on
each live owner and skipping retired/terminal tombstones. Required runtime adds
an off-thread invalidate while two views remain live. CPU interning remains legal
off-thread and is associated with the explicit owner; retired owners reject new
interning. The known source caller in GLMapSurface.updateDisplayDensity queues its
work on the surface thread. Both original public invalidation entry points remain
available; no global CPU cache erasure is performed by this lifecycle.

Terminal ownership controls must retain each actual label, terrain and inner
control wrapper separately across terminal release, invoke safe wrapper methods,
then drop the borrow without manually running its cleaner. The owned probe waits
for weak Java owner collection and a real native terminal-destructor counter
advance. The counter is aggregate evidence; no freed pointer is dereferenced to
identify a destroyed renderer. A timeout fails qualification. Independent source
review and full provider maps remain necessary; Java GC alone proves no GPU
cleanup. Binding/font/shader CPU cache identities remain retained for process
lifetime and have no fixed bound across unlimited view or font creation.


## Independent full rebuild and terrain restart correction (2026-11-14)

A new local experiment rebuilt the pre-correction profile from verified source,
without adopting predecessor objects: 1,238 Java sources, 2,701 classes, 119 JNI
headers and the entire 815-unit native graph (483 Core, 159 JNI, 173 Cesium).
Both libraries, backend privacy and the single SQLCipher owner passed inspection.
All three actual CPU JNI controls passed with zero diagnostics. All 1,326 baseline
Java JNI exports remain present, with 11 added. Local experiment receipt SHA-256:
`5daab0c0d2b839d507f97d23725da609ad958b720777fc5fd47360099bcc662b`.
Independent final source/output inventory review:
`c2a121bd7d3d34511ec955c161c62ff4b49e15754f59d4d5dff938ce747ffb7e`.
These are local integrity records; a portable variant producer and publisher/cache
admission remain separate work.

The real Texture style control also passed its 50 clone/serialization/ownership
iterations with zero JNI diagnostics. Its separate CPU checkpoint is
`2f9e2abe7de98731231bf2f183bdc93b48a1dfcbcc185cb4f46ebcb9a5425fcc`.
It does not exercise URI decoding, asynchronous atlas loading or textured pixels.

The subsequent Xvfb/Mesa lifecycle attempt reached real moved-thread disposal and
resolved all 512 queued Work futures (96 completed, 416 cancelled in the final
pre-correction attempt); both held old workers rejected new submissions. It then
crashed in `GLGlobe::getTerrainMeshElevation` during the first context recreation.
The failed log and JVM crash report remain preserved; no lifecycle acceptance
follows. The release patch cleared its terrain vectors and set `terrainTiles2` to
null, although elevation/picking paths assume a valid vector. The correction
restores the constructor's pointer to the cleared first compute vector. GPU
objects remain deleted and the existing terrain-service fallback is unchanged.
A new complete build and real lifecycle replay must validate this correction;
the earlier successful CPU build is not proof for the changed source.

The corrected source reconstructs exactly from all five locked stages. The genuine
CPU worker control passes again at this source contract, receipt
`f6f29e78c7c4cdb79599b56eabca8976f5503eae2b7193a337ad16354c82fca2`.

The owned headed control now initializes EngineLibrary normally and requires the
actual public resource catalog. Its local resource-only JAR contains the 118
verified payloads plus their catalog, with no production classes or native
libraries. JOGL public listener-disposal calls retain context-before-renderer
ordering on the selected GL thread; removing the view listener prevents an AWT
repaint from reinitializing it before destruction. Real AWT peer recreation must
produce a different created context. Thread/currentness, callback counts and
worker ownership assertions remain mandatory, and disposal-thread failures reach
the main assertion path.

These attempts use an owned Xvfb software display, not the earlier managed Xorg
session. Project JNI diagnostics from managed context/surface callbacks and JDK
font diagnostics are still recorded. Global zero-JNI cleanliness, three complete
recreation cycles, terminal collection and whole-process normal shutdown remain
required. Renderer, SDK packaging and client acceptance remain false.


The corrected full graph compiled successfully in a new output directory (fresh
Java, native translation units and both shared libraries); all three CPU JNI
controls passed again. The native experiment receipt SHA-256 is
`eb003fec8c8a6af4502e5db559887043808e2b0f26c2d5ea17455fb6fe39ac62`.
The following owned lifecycle replay completed three actual context recreations
without the terrain crash. It then failed the terminal shader assertion: the test
used raw canvas destruction rather than the public listener cleanup used for the
recreation cycles. The probe now uses that same context-before-renderer disposal
for every terminal path and requires the fourth cleanup callback explicitly.

The next replay advanced through terminal cleanup, fresh views and borrowed-owner
controls, but hit the unchanged 8 MiB command log quota while emitting JNI warnings.
Its complete bounded output is retained; quota failure is not lifecycle acceptance.
No diagnostics were filtered and no quota was raised. Whole-process completion,
terminal GC results and global JNI cleanliness remain unqualified.


A separate headless font probe loads no Kernel, JOGL or project native libraries.
On the qualified Temurin 17.0.21+9 it completed with 96 JNI warnings; the same
class completed on system OpenJDK 21.0.13 with 39. This isolates an independent
runtime font diagnostic problem; it does not excuse project bridge warnings or
qualify a replacement JDK. The standalone receipt SHA-256 is
`1faeb99506ab83bfc41c1e8910a32f915a55415f4e9fea9874a0229baea250ee`.
The bounded lifecycle log separately contains unchecked managed context/surface
callbacks and a pending-exception warning in `GLMapView.getSurfaceBounds`.

Reproduce the font isolation in a fresh temporary directory (each runtime result
must retain its own complete bounded log and exact JDK identity):

```bash
FONT_PROBE_OUT="$(mktemp -d)"
javac -d "$FONT_PROBE_OUT" takx/kernel-render-context/tests/FontJniProbe.java
java -Xcheck:jni -Djava.awt.headless=true -cp "$FONT_PROBE_OUT" FontJniProbe
```

`FONT_PROBE_COMPLETED` establishes that this font workload returned normally;
it does not override diagnostics or establish renderer acceptance.


The owned managed-context/surface CPU fixture now isolates project callbacks from
font and GL dependencies. The unchanged bridge completed its original 15 throwing
controls with 31 JNI diagnostics. A candidate with explicit upcall exception checks
passes 22 throwing controls and positive value/runnable/listener round trips with
zero JNI diagnostics, four listener removals and two child cleanup calls. It
preserves the exact original throwable, including across cleanup, and refuses
further upcalls with an exception pending. Cleanup retains the primary failure
while attempting all owned listener removals.

This candidate experiment compiled the two bridge translation units into a test
DSO using `-Bsymbolic` against the qualified Native02 dependencies; it is not a
fresh complete JNI library or renderer qualification. Its receipt SHA-256 is
`62c05dc295594eb2a5848d0d6a0d317256e5a11bd216a81c43037c48c6589f37`.
The production profile now locks these two additional files (59 stage paths);
all five stages reconstruct exactly. A new full graph build and the owned fixture
linked to its actual JNI library are required before attributing that result to
the complete variant. The failed missing-classpath, missing-generated-header and
invalid null-runnable-payload attempts remain retained separately.

The strengthened CPU control also throws a distinct secondary exception during
listener and child cleanup. It still returns the exact primary callback throwable
and completes all 22 controls with zero JNI diagnostics. This remains an isolated
candidate result, receipt SHA-256
`947150f3442459362acca39652cd281901a624a2501499f1ba659b53c87cba35`.


The complete variant now rebuilt all 815 native translation units and both shared
libraries from fresh objects; all three CPU JNI controls passed. Native producer
SHA-256: `1b91d535d2b21b1a238c2881ea3a68396fd5ad32b733446fb9f28593eedee874`.
An independent audit verified all 1,399 native files, 1,238 Java sources, 2,701
classes, 119 headers and retention of all 1,326 baseline JNI exports (1,337 total).
Independent review SHA-256:
`aad9ff17d9e057d3667de999e24647e256409d07b12541b63da3b8ae36063866`.

The owned bridge fixture linked to this actual complete JNI library, without
production translation-unit overrides or `-Bsymbolic`, passes the 22 throwing
controls, positive value/native-runnable round trips, four listener removals and
two child cleanup calls with zero JNI diagnostics. It also preserves the primary
throwable when cleanup raises a distinct secondary exception. Scoped CPU bridge
receipt SHA-256:
`b42fbd8fb6cb15072078b2378f78eac9243812c2dd729b3c97f86d1105756305`.
A fresh headed replay is running against these exact libraries. This CPU bridge
result does not qualify fonts, other native bridges, the full lifecycle, a
renderer, SDK or client.


The subsequent owned Xvfb replay completed the functional workload and the JVM
returned normally: three actual context recreations, three fresh context identities,
eleven 512-future worker retirements and three terminal renderer/borrowed-owner GC
controls. All mapped-provider admissions passed. The 7,252,599-byte log stayed
inside its unchanged 8 MiB limit. Strict acceptance still failed: 2,249 JDK font
JNI warnings and one pending-exception warning in `GLMapView.getSurfaceBounds`.
The managed-context/surface bridge warnings are absent. Functional-only receipt:
`8660d8dda97663f514740445ccf2fdaeff6a64a8ca983714dc893271f65cd8fb`.
This is not overall renderer or whole-process zero-JNI qualification.

A separate 62-member lookup probe isolated the remaining project mismatch:
`FeatureLayer3.Options.labelHints` was absent. The canonical client profile already
adds that field with the native default policy; the renderer composition had
selected the JNI changes while omitting their paired Java class. The profile now
selects all three source sections, locks 60 stage paths, and rejects a missing or
old paired Java image in its offline contract guard. It does not remove the field
access, invent an API alias or discard requested label flags.

A local control with only the exact paired Java class overlay and the actual
Native03 JNI library passes all 62 lookups plus typed options/envelope marshaling
with zero JNI diagnostics (defaults, requested flags, filter, visibility and null
refusal). Paired-source control receipt:
`d8f9b6d559eafabf1a34ee9d784f4e12da3268d77350ba285954afbcbd2e91d8`.
Its scope is an explicit Java contract overlay; it is not a complete variant.
All five revised source stages reconstruct and ten offline guards pass. A new
complete Java/native build and direct controls against those classes/libraries
remain required before a new headed replay. JDK font/global JNI, SDK and client
gates remain open.


The paired-source variant rebuilt all 815 units and both libraries with the complete
fresh Java graph. Producer SHA-256:
`7e56012b62cdd7c4c70ccfce48c79e63bb27e56a440cb3465b034452a752904a`.
Its independent source/output review is
`1e24e5735810d5ab09011b439c9b4614ba3bdfb8aac519b3818832929a89736d`.
Direct actual-library controls pass with zero JNI diagnostics: the 22-case bridge
receipt is `90c02b0cf998145911e6efba98163ec38c754363f94ca4b70c5efcb86a90855d`,
and the 62-lookups/typed-options/envelope receipt is
`09189aaa711f8abd2149f5d8c2c2b87a89beb93716733b0e90bced690e9a04b3`.
The latter also compares Java default hints to independently constructed native
options and uses the full new classes directly, without a class overlay.

Its owned headed JVM again completed all functional controls and returned normally.
All 2,267 remaining JNI warnings originate in JDK font routines; no project JNI
warning remains in this workload. Strict overall acceptance is still rejected.
Functional-only receipt SHA-256:
`7ba68d0e8575ab983eeb353e5413ee67c66ee4896de3f439293224273e135a9d`.

A separate mixed-surface CPU regression demonstrates a shared-state defect: the
managed bridge cached RenderSurface2 mode globally, so constructing a legacy
surface changed an existing modern surface's physical dimensions from 160x120 to
80x60. The correction removes that shared flag and checks the actual instance type
in each getter, preserving the class ABI. The isolated one-unit candidate passes
both construction orders and 100 concurrent calls with zero JNI diagnostics;
receipt `a3c62a522a25824dc99893a7cbe0efa77309ba3e4f714934ee5e0c141be7e153`.
That source is now included in the locked patch. All five stages and ten offline
guards pass. A complete rebuild and direct mixed-interface regression are still
required for this new source; the earlier full variant is retained separately.


The mixed-surface correction now passes a complete fresh 815-unit rebuild and all
three CPU JNI controls. Native producer SHA-256:
`1142251f81f2ffe3e37e9de0e463ab715cc3b7b5bfce6c6a2107cc10cb3a7125`.
Independent review:
`51670cc0d160a4d169e51b5cb9c596add74fa83b6dccb2741f5358dbab30e0c8`.
Actual-library, zero-JNI receipts cover the 22 bridge cases
(`49bef5edf53a8ef8bcdab48d82d4b3fc9d93644c4998924eb1a95b7daa09baf8`),
62 lookups and typed options/envelope cases
(`4588ce38b587fcf812e2deb90f1b6c1c4983cab7ebe5a82992ea451bfdb81403`),
and both mixed-interface construction orders plus 100 concurrent calls
(`ddaceb70ac180e792859cb0de23d8b9342a4372000639ca0553e72006d5bdd74`).

Its headed JVM again returns normally after all functional controls. There are
zero project JNI warnings and 2,249 JDK font warnings in the 7,245,835-byte log;
strict overall acceptance remains false. Functional-only receipt SHA-256:
`602904fc540733ad32d1d88e88de98cc220363f55f91db34b66edf3730750112`.
The original Temurin runtime remains unchanged. Matching official OpenJDK source
is being used for an independent, unmodified font-module rebuild baseline before
attempting a runtime correction. No derived runtime, full renderer, SDK, client or
portable-producer acceptance follows from these scoped controls.
