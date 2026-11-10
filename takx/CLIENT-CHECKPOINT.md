# TAKX client feasibility checkpoint

The shipped Java compiler proves the complete **engine, port and annotation
desktop profile**: 862 engine, 77 port, six annotation and 59 adapter sources.
The explicit `--scope engine-shared` option additionally compiles all 231 shared
desktop sources: 212 in `src/main/java` and 19 in `src/jre/java`. Neither scope
assembles a complete Kernel SDK or compiles either TAKX client.

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

## Current production compiler checkpoint

The public WorldWind [source recipe](worldwind-java/README.md) builds the complete
NASA Java tree under an explicit standard-GDAL-RGB project profile. All 189
resources and required licenses are retained. A renderer-import patch lets a
20-source consumer slice compile for both TAKX profiles; it does not establish
complete client compatibility or provide the private TAKX-4 artifact.

Local production probes additionally use six genuine source-built UI candidates,
verified Kernel public dependencies, 70 real XJC sources, two generated templates
and the actual AutoValue/EventBus processor graph. The UI candidates retain their
own identities: colorchooser is the original author's 1.5 rather than requested
1.1; the wizard is a preserved-source reference rather than an established match
for `rev-28122010`. They are not accepted as equivalent runtime replacements.

| Actual compiler scope | 5.7 | 5.8 |
| --- | --- | --- |
| Complete Bootstrap main/preferences and ProcessManager Java | 18 sources, 22 classes, pass | 18 sources, 22 classes, pass |
| Platform main plus real generated inputs | 1,811 supplied sources, fail | 1,877 supplied sources, fail |
| Initial Platform type-resolution diagnostics | 1: `TextureFillStyle` | 18: texture, contour and vehicle APIs |

The failing Platform runs emit no accepted classes. Their 17 AutoValue-generated
sources are retained only as diagnostic output. Initial diagnostics are not
full-client error totals; later member/API differences can remain. Client,
AspectJ/checker instrumentation, packaging and runtime acceptance have not passed.

[`TextureFillStyle` needs real native rendering support](https://github.com/jonathanagustin/uds-takserver/issues/424):
the inspected public Kernel lacks its native style/JNI factory and polygon
UV/shader integration. Published-shape crosshatching cannot be supplied by an
empty wrapper or a solid-fill alias. Repeat values, rotation/dimension units and
serialization need an authentic contract or explicit project semantics.

The source-built CommonCommo transport proof validates mutual-TLS certificate
trust against a loopback peer; it does not verify server hostnames or demonstrate
TAK Server interoperability. A complete native Kernel/GIS/GL runtime, map
rendering, application resources, identity checks and live client acceptance
remain open. Neither TAKX desktop nor Kasm/offline packaging is ready to ship.

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

The adapter now supplies `Paint.measureText(String, start, end)` with the pinned
Android range and pixel-rounding contracts. A fresh run of all 1,235 combined
sources succeeds with zero errors and four warnings. The unchanged
`RolesManager` consumer is exercised using a real asset and glyph-position
checks. The failed probes' partial class outputs are not accepted artifacts.
This investigation retained separate source, classpath and output receipts and
used bounded javac only; it ran no native build, renderer or client. The reusable shared scope locks its full compile classpath and defaults to
patched Jackson versions. Its [recorded advisory assessment](kernel-java/shared-advisories.json)
returns no findings for 33 patched classpath coordinates; that is not a complete
runtime dependency audit. The original Jackson 2.13.1 classpath remains an
explicit historical baseline.

The real patched CommonCommo JAR is still 1.17.2. Its SHA256
`7563ec3978c7ff7c39ff2525b04dfcb9b9905ea175904e2393edae703b24ce4e`
matches the existing native foundation receipt. A fresh typed compile verifies
`configKnownEndpointForContact(String, String, String)` returns `Contact`.
All 36/37 distinct method names used by the two inspected Commo managers are now
present, but that name inventory is not compilation of either complete manager.

With the shared output included, the refreshed import inventory returns to the
two/eighteen source-absent imports. It still does not test all members or compile
either client. Both clients still require their full dependency
closure, including custom WorldWind `2.2.1-TAKX-4`, full source/API
compatibility checks, resources/packaging, native GIS/GL/Kernel
linkage, map rendering/recovery, enrollment and CoT interoperability. The earlier shared-module checkpoint did not include a full client compiler
recipe/classpath; its artifacts were inventories and module probes. The newer
Platform probes above remain bounded failed compilations, not accepted clients. The current
foundation work does not establish a functioning TAKX application.

CDI Blacksmith `1.1.3` remains an upstream **test-suite** dependency, not an
established production runtime requirement. Both pinned clients declare it via
`gradle/standardTestSetup.gradle` (`testImplementation`); the TestSupport module
exports it for test consumers, while application assembly excludes that module.
See the [WorldWind source recipe](worldwind-java/README.md) for exact source pins
and the limits of the independently built public-source profile.
