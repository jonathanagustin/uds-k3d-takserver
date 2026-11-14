# Failed software contour drawing controls

`ContourDrawProbe.java` is a source-locked diagnostic, not part of the passing
headless control inventory. It needs the actual context admission helpers from
PR #499, frozen full Native07 providers/classes, JOGL, an independently owned
Xvfb display and the separately qualified private derived font runtime. It is
not a standalone native builder or a stock-JDK/hardware/client qualification.

The probe uses the actual public elevation registry, clipped project contours,
native styles/features, persistent FeatureLayer3, registered real batch renderer
SPI and GLMapView. No fixture draws the colored lines. The first hidden baseline
has zero target-color pixels; enabling the layer yields 814 green major-contour
pixels and 268 magenta minor-contour pixels in the retained 320×240 frame.

Both retained runs fail. The first lacks the host framebuffer clear; the second
matches pinned TAKX 5.8 `JOGLMapRendererSpi.display` by clearing color/depth/stencil
before `GLMapView.render`. Hiding the layer still leaves target pixels after the
bounded frame pump. The reason has not been established. The second run also
emits 18 strict JNI diagnostic lines; direct Java native frames identify
`NativeLayer.wrap`, `NativeFeatureDataStore4.wrap` and `GLMapView.start`. Other
worker warnings require native trace attribution; no C++ callsite is inferred.
All input hashes are reverified after both failures. Actual Core/JNI producer
bytes are unchanged. The screenshot is functional evidence only: no drawing,
visibility, renderer, full SDK or client acceptance is granted from these runs.

Logs, source, helper, compiled classes, synthetic datastore, screenshot and
independent review remain in separate local qualification roots:
`contour-draw-controls-01` and `contour-draw-controls-02`. The second source is
published here for review; default verification fingerprints it but compiles and
executes only the headless CPU controls. Next work is strict-JNI attribution and
visibility/cache invalidation diagnosis, followed by a full fresh producer and
owned-display replay for any native correction. The zero-diagnostic and negative
visibility gates remain mandatory.

## Native warning attribution

A third, diagnostic-only run uses native write-stack tracing on the unchanged
full Native07 library. Fourteen warning writes yield nine distinct native stack
prefixes. Symbol resolution identifies these review targets:

- Core `ManagedLayer.cpp`: constructor calls before interface marshaling.
- Renderer core `ManagedGLLayerSpi2.cpp`: factory creation and marshaling.
- Renderer core `ManagedGLLayer2.cpp`: constructor/subject marshaling.
- Feature `ManagedFeatureDataStore2.cpp`: constructor and query callback paths.
- Feature `Interop.cpp`: query-parameter marshaling.
- Feature `ManagedFeatureDefinition.cpp`: raw geometry and raw style callbacks.

The trace, exact library/source/tool hashes and symbolized prefixes are retained
in `contour-draw-controls-03/warning-attribution.json`. Partial unwind prefixes
are reported only as observed; missing frames are not inferred. Tracing changes
timing: this run fails its visible-color condition before completing the hide
test, so it is attribution evidence rather than functional acceptance. Review
pending-exception checks and cleanup in these actual callback paths before any
closed source correction and complete fresh native rebuild. No native producer
or acceptance gate was modified for the trace.
