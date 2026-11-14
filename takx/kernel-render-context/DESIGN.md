# Project RenderContextControl for Kernel 8.30.5

The pinned TAKX 5.7/5.8 callers stop and release the view while the old GL context
is current, destroy that context, then install a new JOGL context, reconfigure
and start the same view. This is a project implementation of that observed
contract; it does not rename the upstream Kernel version or claim unseen newer
Kernel semantics.

A per-view functional context/surface binding keeps the native RenderContext&
address stable while forwarding to the actual current platform context. The
renderer, terrain and existing native interop references retain their owners;
no renderer pointer is replaced underneath clients. Context replacement is
permitted only after stop/release on the old GL thread and on the new current
GL thread. Running, null, child/shared ownership and wrong-thread transitions
fail explicitly. Actual com/gov context and surface interfaces must be adapted
with complete forwarding, including size listeners and physical dimensions.

Release drains generation-owned work on the old GL thread before GPU release,
then removes only that view binding's shader/text/fixed-pipeline/worker caches.
The generation retires old drawable callbacks so they cannot issue commands
against a new context. Late producer work is an explicit lifecycle error, not
silently executed on the replacement context. Native pooled-event ownership
must be checked alongside Java task ownership. Shared live views must not be
subjected to blanket cache eviction; the first supported rebinding contract is
an unshared main context with explicit multi-view guards.

JOGLRenderContext must itself implement the real GLEventListener lifecycle so
the caller can remove it. Thread/current-context checks must use the actual
captured GLContext, not the current queue-only thread assignment. New bindings
must not accidentally recognize a replacement drawable context as the old one.

The portable source preparation and offline guards do not invoke a native build.
A separate local native/CPU qualification has passed; GPU lifecycle is still a
required independent gate. All source changes live in a new pinned official projection and a separate
feature patch; accepted prefixes and consolidated native profile locks remain
unchanged. A headed JOGL/Mesa test must exercise real rendering/readback, resource
and queue lifecycle, repeated unshared context destroy/recreate, rejection paths,
listener cleanup, and strict JNI checks before this feature is accepted. Merely
compiling the interface, returning a null control or clearing a framebuffer alone
is insufficient evidence.

## Experimental CPU retention limit

GPU retirement preserves borrowed native GLText2 and Shader CPU objects. Native
cache entries for every created font/context/thread slot remain owned for process
lifetime. This is not a fixed memory bound across unlimited view or font creation;
memory reclamation is not qualified by this experimental profile. Java GLText GPU
overloads check their retained context before entering native code; metrics use
only the Java text-format object. Shader APIs reject a retired binding and reject
failed program creation. A public raw shader handle becomes zero at retirement;
reading that field alone is not evidence of successful rendering.

Required headed tests explicitly invoke retained GLText draw/batch and Shader.get
after terminal disposal, require exceptions before native GPU work, retain both
objects through rebind and verify actual recreated rendering. Two simultaneous
views and one context moving between GL threads must remain isolated. No native
cache entry is erased by this lifecycle. The unrelated global text-format-factory
reset is not part of this lifecycle or its acceptance scope.

Terminal binding identities and their native peers are also retained for process
lifetime so cache keys cannot be recycled by an allocator for a new view. This is
an explicit ownership registry, not reliance on current JNI global-reference
cycles. After renderer destruction the terminal binding clears its delegate and
rejects operations; the binding no longer delegates to that drawable. Existing JOGL/native peer
registration cycles may still retain the retired wrapper/drawable metadata;
collection or memory reclamation is not qualified. This adds unbounded
per-created-binding tombstone retention. The native wrapper and its surface peer
remain alive while cached borrowed pointers can exist. Qualification must dispose
view A and repeatedly construct fresh views C while invoking old A borrows and
checking fresh resource identities and live view B isolation.

Java GLLabelManager and terrain wrappers retain their GLMapView owner; builtin
renderer controls are nonstatic inner classes. Terminal disposal must not manually
clean the native view behind these wrappers. Scoped native layer-control visits
currently construct factory wrappers with null owners; this profile does not
extend their lifetime beyond their valid visitation/renderer ownership scope.
Final native destruction after GPU release must avoid queueing work on a retired
context. This remains a source ownership review gate until the native terminal
teardown path and genuine headed controls are complete.
