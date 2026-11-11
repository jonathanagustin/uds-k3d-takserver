# Render-context project variant qualification

Status: experimental source profile. Native linking/static audits and five CPU
JNI controls have passed locally. Headed/GPU lifecycle remains unqualified.
The actual upstream identity remains Kernel 8.30.5 at official commit
9f6893dd657feacc35ec5de03dad721c2e44170e.

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
