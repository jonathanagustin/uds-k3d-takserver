# Pre-realization source audit

Source-only review, 2026-11-11. No native build, GL execution, download, push,
or frozen evidence modification was performed by this audit.

Both official 5.7 and 5.8 Client sources have the same relevant ordering in
`gov/takx/core/globe/tak/JOGLMapRendererSpi.java`: create the component, call
RenderContextFactory.create, construct GLMapView, configure it, and only then add
the listener whose init starts the renderer. A new component can have zero size.
The official client JOGLRenderContext implements com.atakmap.map.RenderContext;
Java therefore selects the com overload, not the new gov overload.

The candidate GLMapView com overload now installs a stable RenderContextBinding
for contexts other than GLMapSurface. The gov overload goes directly to the
protected constructor with its own binding, so there is no double wrapping.
GLMapSurface owners retain their previous constructor path and lifecycle. The
protected boolean legacy path remains unchanged. The actual TAKX call now reaches
the existing binding-dependent RenderContextControl registration.

Native jglmapview.cpp create validates pointer ownership and constructs GLGlobe.
GLGlobe.cpp:1028 initializes GLGlobeBase, ElMgrTerrainRenderService, scene math,
controls and GLGlobeSurfaceRenderer. GLGlobeBase.cpp:111 allocates CPU label/control
state; GLLabelManager.cpp:114 initializes CPU/protocol-loader state.
ElMgrTerrainRenderService.cpp:527 constructs terrain CPU storage and callbacks.
SurfaceControlImpl -> GLGlobeSurfaceRenderer.cpp:111 -> GLMegaTexture.cpp:20
constructs descriptors only. GLGlobeBase_glScene is matrix math, not GL calls.
The atmosphere/stars setters only assign flags. No current-context requirement or
GPU allocation was found in this construction path. GLGlobe uses the Globe's
width/height for its scene, not its passed component bounds; public Globe()
initializes 1920x1080. This is source reasoning, not native execution evidence.
CurrentRenderContext.setCurrent records Java/native TLS ownership; it does not
create or make a GL context current. No bootstrap GL context was added.

A separate real zero-size problem existed in Java GLMapView construction:
its initial MapSceneModel used the surface dimensions before realization.
MapSceneModel2 camera construction divides width by height and its transform
must be invertible. The constructor now uses Math.max(1, surface dimension) only
for that provisional CPU scene and its focus. The surface getters, physical
surface sizes, native context and drawable are unchanged. Native GLGlobeBase::start registers its surface listener and reads the actual
surface size into state, render-pass bounds and viewport. Later native
onSizeChanged calls setSurfaceSize, which rejects zero sizes and queues
glMapResized. Real size events and the normal render sync/scene validation replace
provisional CPU scene data. The Java sizeChangedHandler exists but no registration
was found in this source; the native listener is the demonstrated update path. There is no synthetic GL context
or claim that a 1x1 drawable was rendered.

Final freeze still requires regenerated patch/preimages and source hashes,
Java compile verification of these final edits, native dependency closure and
header consistency review, and all genuine headed lifecycle controls already
listed in QUALIFICATION.md. The source-only positive dimensions change is not
proof that every custom zero-dimension Globe construction is valid: the public
Globe default is the examined client path. Terminal destructor/cache ownership
and failed-rebind cleanup must retain their independent source/runtime gates.
