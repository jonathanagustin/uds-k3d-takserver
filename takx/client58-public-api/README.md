# Public 5.8 vehicle metadata profile

This project profile implements vehicle-model CoT metadata through the real
public Kernel `ICotDetailHandler2`, `CotEvent` and `CotDetail` APIs. Its generic
Interop callback matches the pinned TAKX 5.8 caller. It does not create vehicle
meshes, implement contours, or identify public Kernel 8.30.5 as private 9.12.6.

The locked public Android handler establishes the `model` wire fields: vehicle
type, category, name and outline. The pinned 5.8 caller additionally expects
stroke/fill color callbacks. This project policy exports both colors and gives
fill precedence for a model's single color. Signed decimal, unsigned decimal and
32-bit hexadecimal ARGB values are accepted; malformed values fail before the
handler mutates callback-owned state. Colors may precede a valid vehicle model
in an incoming event. Unrelated model types are ignored. Callback exceptions
propagate without replacement. Asset availability belongs to the caller's
`setVehicleInfo` callback, which can refuse an unavailable model.

`inputs.lock.json` records both source revisions and their source hashes. The
new handler is an explicit project implementation, not a recovered private
implementation. Its controls use actual public CoT classes and an owned test
model. Thirty-four checks cover wire round trips, color order/precedence,
invalid/missing fields, callback refusal/error preservation and absence of SDK
native libraries. No full Client or mesh runtime acceptance follows.

Default verification and four offline guards need no Java or downloads:

```sh
python3 build.py
python3 -B -m unittest discover -s . -p 'test_*.py' -v
```

The opt-in controls consume the independently reviewed SHA-256 of a complete
`public-context-client-java` receipt (1,239 sources / 2,702 classes), all of its real JARs,
and an explicit JDK. They verify all class/dependency hashes before and after
execution and preserve failures in a fresh, disjoint output directory:

```sh
python3 build.py --phase controls --java-proof /path/to/full-java-proof \
  --java-proof-sha256 REVIEWED_RECEIPT_SHA256 --java-home /path/to/jdk17 \
  --output /path/to/new/vehicle-controls
```

The profile downloads and installs nothing. The complete 5.8 Platform/Client,
contour generation/layers, real vehicle assets/meshes, peer interoperability and
portable SDK assembly remain separate qualification gates.

The composition recipe is staged in #499 as `takx/kernel-render-context/client_java.py`. Its source revision and reviewed native/Java input receipts remain explicit prerequisites; this metadata profile does not build them or silently select a legacy checkpoint.
