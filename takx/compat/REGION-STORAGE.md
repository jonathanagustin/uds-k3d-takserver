# Fixed-shape region storage helper

The package-private `Bitmap.replaceDecodedRegion` helper supports the separate
region decoder without reusing the full-image reshape operation. It copies a
validated, positive-size, strided ARGB rectangle into the origin of a mutable
owned target, retaining target dimensions, capacity and the exact allocation.
Immutable, recycled and borrowed targets are rejected. All row/range checks
complete before any mutation. Invalid source ranges preserve pixels and alpha
metadata.

When alpha metadata changes, the current Java2D view is rebuilt over the same
storage. An opaque-to-alpha transition first normalizes previously visible
opaque pixels to alpha255 so untouched destination rows retain their visible
colors. This is an explicit desktop storage policy, not a claim about Android
native raw bytes. An alpha-to-opaque transition makes the entire destination
opaque. Same-alpha writes preserve the current Java2D view identity.

`test-region-storage.sh` runs 15 storage checks, including exact allocation
identity, source stride, untouched pixels, metadata transitions, unchanged
state on invalid ranges and lifecycle/ownership rejection. It tests a real
storage helper, not a substitute BitmapRegionDecoder or native decoder.
