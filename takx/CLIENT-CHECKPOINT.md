# TAKX client feasibility checkpoint

The shipped Java compiler proves the complete **engine, port and annotation
desktop profile**: 862 engine, 77 port, six annotation and 59 adapter sources.
It does not compile the separate `takkernel/shared` module, assemble a complete
Kernel SDK or compile either TAKX client. The shared module adds 231 desktop
sources: 212 in `src/main/java` and 19 in `src/jre/java`.

Both official clients remain candidates; prefer 5.8 after actual client and
runtime acceptance. The source and artifact identities remain distinct:

| Profile | Official TAKX revision | Declared Kernel | Declared CommonCommo |
| --- | --- | --- | --- |
| 5.7 | `0b59a9bb2d0e90dc35c9edfff1c2056daab2b713` | 8.57.11 | 1.20.0 |
| 5.8 | `af54a3e1fe8796b6e109e2e5925dbef524ea7e31` | 9.12.6 | 1.22.3 |

Our public candidate is Kernel 8.30.5 / CommonCommo 1.17.2 at official ATAK
`9f6893dd657feacc35ec5de03dad721c2e44170e`, with the documented desktop adapters
and streaming-contact patch. These artifacts have not been renamed to either
client's required versions.

## What the earlier numbers mean

The earlier “two missing types for 5.7 / eighteen for 5.8” findings were explicit
source-import inventories, **not compiler-error counts**. They indexed public
Kernel source including `shared`, whether or not those sources had compiled.
The 2026-11-10 refresh against exact Git source snapshots reproduces those
counts: 442 relevant import entries for 5.7, 464 for 5.8. It verifies 3,519 and
3,588 client main Java source files respectively, including main AspectJ Java
files absent from the older sparse 5.7 working tree. Neither client was compiled.

Against the actual engine/port/annotation output, the remaining inventory is:

| Inventory measure | 5.7 | 5.8 |
| --- | ---: | ---: |
| Imported types absent from the public source inventory | 2 | 18 |
| Referenced `shared` types present in source but not in the compiled profile | 88 | 90 |
| Unresolved import entries against that compiled profile | 148 | 166 |
| Of those, static import entries | 60 | 60 |

Import entries include static members, so the latter totals are neither distinct
missing-type counts nor javac diagnostic counts. Presence of an enclosing class
does not establish its method, field or constructor compatibility.

Both clients lack `RenderContextControl` and `TextureFillStyle` in the public
source candidate. The 5.8 inventory additionally lacks eleven contour types,
three vehicle types and the APP6d/2525E-change-1 symbology providers. These are
real feature gaps; removing their imports or supplying empty replacements would
not establish compatibility.

## Bounded shared-module diagnostic

A separate local investigation compiled **all 231 unchanged shared desktop
sources**, using the verified engine/adapters output and exact public dependencies
from the pinned shared Gradle declarations and their POMs. An initial incomplete
classpath produced 274 diagnostics; adding the five declared renderer transitives
reduced the genuine compiler result to one error:

```text
RolesManager.java:262: incompatible types: String cannot be converted to char[]
paint.measureText(abbreviation, 0, abbreviation.length())
```

The adapter lacks `Paint.measureText(String, start, end)`. This is the next
concrete API repair and consumer test, followed by another full shared compile.
The failed probe's partial class output is not an accepted shared artifact.
This investigation retained separate source, classpath and output receipts and
used bounded javac only; it ran no native build, renderer or client. Its original
Jackson 2.13.1 and symbol-renderer classpath is compilation evidence, not a
runtime dependency recommendation. A reusable shared profile needs its own
reviewed dependency/advisory assessment.

The real patched CommonCommo JAR is still 1.17.2. Its SHA256
`7563ec3978c7ff7c39ff2525b04dfcb9b9905ea175904e2393edae703b24ce4e`
matches the existing native foundation receipt. A fresh typed compile verifies
`configKnownEndpointForContact(String, String, String)` returns `Contact`.
All 36/37 distinct method names used by the two inspected Commo managers are now
present, but that name inventory is not compilation of either complete manager.

After shared compilation, both clients still require their full dependency
closure, including custom WorldWind `2.2.1-TAKX-4` and CDI Blacksmith `1.1.3`,
full source/API compatibility checks, resources/packaging, native GIS/GL/Kernel
linkage, map rendering/recovery, enrollment and CoT interoperability. No frozen,
complete client compiler recipe/classpath was available to rerun in this
checkpoint; the older artifacts were inventories and module probes. The current
foundation work does not establish a functioning TAKX application.
