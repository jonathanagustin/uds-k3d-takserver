# Public-source textured polygon feature (in progress)

This is a project feature patch for the pinned public Kernel **8.30.5** source,
not the private Kernel 8.57.11 or 9.12.6 implementation. It targets the actual
8-argument constructor used by both pinned TAKX clients. No SDK version alias,
fake native pointer or solid-fill substitute is used.

The official client contract supplies a URI, ARGB tint, per-axis repeat/stretch,
width/height, rotation and north/screen anchoring. It does not document the
private numeric constants, units or serialized representation. This variant
explicitly uses positive **display-pixel dimensions**, **clockwise degrees**,
repeat=0/stretch=1 and a versioned project OGR BRUSH id. These choices need
application review; matching a constructor does not establish private SDK
compatibility.

The patch adds a real native Style with Java/JNI ownership, getters, class
dispatch, clone/equality and serialization. The optimized production path is
`GLGeometryBatchBuilder` → `GLBatchGeometryRenderer4` → polygon shader. Each
textured feature retains its own material beside the existing atlas handle.
Actual projected triangle positions determine stretch bounds; north is derived
from the feature's geographic origin and actual batch projection. Sampling
rotates around the projected origin. Repeat wraps inside the image's atlas
subrectangle, inset half a texel to avoid neighboring image bleed. Transparent
texture overlays remain separate from preceding solid fills. Existing upstream
multi-ring tessellation supplies holes unchanged. Hit testing keeps polygon
geometry rather than treating transparent hatch pixels as absent geometry.

A distinct texture callback reuses the actual asynchronous bitmap loader and
atlas, with a separate ready cache and no default point-icon substitution.
All active texture styles are preflighted before any part of a feature is
emitted. Pending or failed texture features emit no partial composite; ordinary
siblings continue. Each feature records None/Ready/Pending/Failed. Actual load
completion triggers the existing refresh; an asynchronous texture failure
triggers one terminal refresh even when ordinary icon fallback is disabled.
Permanent failures are reported without retrying an unchanged URI or busy-spin.
Ordinary recursive error behavior remains upstream's behavior. Texture-bearing
style resets preserve nested level-of-detail limits; a later stroke is separated
from a textured fill. These changes still require the full runtime gate below.
No separate atlas lifetime or global GL_REPEAT change is introduced. Context
recreation acceptance depends on the independent render-context feature.

Small local controls currently pass:

* Real production UV/frame math: repeat, negative coordinates, mixed stretch,
  rotation, north versus screen anchoring, viewport offset and invalid input.
* Six changed real C++ translation units pass syntax checks using the accepted
  compiler/dependency flags. The two actual Java source files compile and emit
  their genuine JNI declarations.
* The actual production polygon shader renders upstream multi-ring tessellation
  under real source-built GLES and Mesa software EGL. Three create/destroy
  cycles each check 8,192 interior pixels across repeat, rotation and mixed-axis
  modes; the hole remains clear and another atlas image does not bleed.

The pixel control uses an owned asymmetric texture fixture. It does not yet
exercise URI decoding, asynchronous atlas loading, the complete batch builder /
renderer object lifecycle or a TAKX drawable. The separate composed Native03 +
CPU04 qualification now passes the five Texture CPU JNI methods and native clone
ownership/getter checks under `-Xcheck:jni`. A later full-style CPU control passed
50 repetitions of composite child order/value, parser serialization and owned
clone disposal with zero Java Native Interface (JNI) warnings. The first failed
control remains preserved: upstream whole-composite equality compares child
pointers, so independent parsed children require individual value checks. See
[qualification evidence and limits](QUALIFICATION.md). These CPU checks do not
establish image decoding, asynchronous atlas loading, the complete native
texture feature or live client acceptance.
Perspective/horizon behavior, surface render-to-texture pixel density, global
wrap/pole behavior, atlas eviction/context recovery and performance remain
acceptance gates. A vertex behind the camera or a degenerate texture frame is an
observable error, not an accepted fallback.

No ordinary server build, package or CI workflow enables this feature.

Source preparation and offline guards:

```sh
python3 -B -m unittest discover -s takx/kernel-texture -p test_prepare.py -v
python3 takx/kernel-texture/prepare.py --source /path/to/pinned-official-source --output /new/owned/overlay
```

The output contains only changed/new feature files and a preparation receipt;
it is not a complete Kernel source distribution. It refuses a different Git
revision, wrong preimages, links, existing new files or any existing output.
`texture-fill.patch` can also be applied with fuzz zero to a separately staged
full source tree after the same preimage checks. Other project Kernel patches
remain separate. Native controls are opt-in and require the reviewed complete
Kernel/GLES provider inputs; default guards perform no compiler/native/network
execution.

The opt-in `builder-control.cpp` exercises the real builder with explicit
callback fixtures: first-pending and terminal-failed texture followed by an
ordinary solid sibling, pending-to-ready retry, no icon callback substitution,
both texture/stroke orders and nested level-of-detail bytes. It has passed
syntax checking only and has not been linked or executed. It does not prove the
actual asynchronous loader/atlas runtime. The query callback, atlas failure,
refresh scheduling, siblings and edit-overlay path need a separately reviewed
full builder/renderer runtime qualification. Public struct/vtable layouts change;
never mix only the edited objects into an accepted old Core. The historical
standalone Ninja estimate identified 78 affected objects (about 6.65 MiB of then
current object bytes), plus Core/JNI relinks. The actual composed Native03 build
compiled **108 affected objects** and relinked Core/JNI with the other reviewed
project overlays. That is a composed-variant closure result, not a new standalone
Texture build or an execution of `builder-control.cpp`. A standalone variant
still needs its own dependency scan. External source-built providers can be
reused by identity.
