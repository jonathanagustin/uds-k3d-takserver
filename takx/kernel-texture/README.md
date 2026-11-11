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

The existing asynchronous icon/bitmap cache is reused for URI loading and atlas
ownership. Missing textures return the cache's error instead of silently
substituting a solid fill. Recursive collection/composite/level-of-detail calls must now
propagate those errors. No separate texture lifetime or global GL_REPEAT change
is introduced. Context recreation acceptance depends on the independent render
context feature and remains unproven here.

Small local controls currently pass:

* Real production UV/frame math: repeat, negative coordinates, mixed stretch,
  rotation, north versus screen anchoring, viewport offset and invalid input.
* Five changed real C++ translation units pass syntax checks using the accepted
  compiler/dependency flags. The two actual Java source files compile and emit
  their genuine JNI declarations.
* The actual production polygon shader renders upstream multi-ring tessellation
  under real source-built GLES and Mesa software EGL. Three create/destroy
  cycles each check 8,192 interior pixels across repeat, rotation and mixed-axis
  modes; the hole remains clear and another atlas image does not bleed.

The pixel control uses an owned asymmetric texture fixture. It does not yet
exercise URI decoding, asynchronous atlas loading, the complete batch builder /
renderer object lifecycle or a TAKX drawable. No linked JNI style round-trip,
complete native feature qualification or live client acceptance has passed yet.
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
