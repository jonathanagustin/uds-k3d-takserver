# Genuine LibKML source profile

This opt-in Linux profile builds all six real LibKML 1.3.0 libraries from the
pinned official TAK source archive and PGSC patch: base, DOM, engine,
convenience, regionator and XSD. Its 112 whole production translation units
come from the official Makefile source lists. It uses C++17 and PIC, with no
source extraction, feature filtering, stubs or host-library fallback.

The Expat provider is genuine **2.10.0**, the official stable release published
2026-11-02, verified against the upstream release asset SHA256. This is an
explicit supported-provider choice, not a relabeling of TTP's Expat 2.1.0.
Current upstream CMake builds the real library with tools, examples and tests
disabled. The old TTP platform patch is retained for source provenance but is
not applied: its autotools scripts and xmlwf changes are not used by this
native CMake profile. A strict preparation attempt against the legacy archive
failed on mismatched config.sub context; that evidence remains preserved.

Existing providers are reused only after inventory, source, recipe, tool and
positive-control checks: actual Boost 1.77.0 headers from the LibLAS producer,
zlib 1.3.1 from the Assimp producer, and the genuine four-TU LibKML-prefixed
minizip archive with its recorded CRC type patch. The URI provider is actual
uriparser 0.9.8 from the verified Cesium dependency producer. LibKML is compiled
against those real headers and APIs; no stock symbol is renamed or aliased to
satisfy a fork. URI resolution, normalization, filename conversion and invalid
URI controls exercise this provider choice.

Run `build.py` with a new external `--output`, pinned `--libkml-archive` and
`--expat-archive`, verified `--las-proof` and `--assimp-proof`, and the
`--minizip-root`, `--minizip-proof`, `--cesium-proof` and
`--cesium-stopped-snapshot` inputs. It does not download or install packages.
The bounds are 32 MiB consumed compressed source, 512 MiB expanded source,
2 GiB output, one compilation job and a 20-minute total command deadline.
Owned subprocess groups are killed on timeout, excess output or disk budget.
Failures and earlier proof directories are retained.

Acceptance requires a strict shared link of every object in all six KML
archives and their real providers. Static Expat is linked with
`--exclude-libs,libexpat.a`; any `XML_*` dynamic symbol fails the guard. The
final Kernel link must retain this isolation when incorporating the static
Expat archive. The actual Expat version and positive/malformed XML parser are
checked separately. The real KML consumer verifies parsed DOM names and
coordinates, KMZ disk and memory roundtrips, missing paths/members, malformed
XML, non-ZIP input and the exact loaded shared provider plus system runtime.
Receipts bind sources, patches, tools, configuration, installed products,
objects and controls. These are local integrity records, not authentication
against a hostile metadata author.

This provides the direct KML dependency required by the full Kernel source.
It does not enable the previously disabled GDAL LIBKML driver or change that
reduced format profile. CURL detection in upstream configure enables network
examples; the official PGSC patch already omits examples. All original
convenience HTTP-client code is retained: its upstream default SendRequest
performs no I/O and applications supply a transport. Network behavior is not
accepted here. Full Kernel, JNI, SDK assembly and client acceptance remain
separate genuine integration gates.
