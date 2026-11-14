# TAKX 5.8 elevation-download compatibility source profile

Experimental compatibility profile; the offline behavior controls pass, while
complete Platform and client acceptance remain open. The new public Kernel
component leaves four real `ElevationDownloader` contract errors in the official
TAKX 5.8.1 Platform. This profile changes genuine source; it supplies no empty
API (application programming interface), fake terrain samples or version alias.

`source-profile.json` pins both official revisions, complete pre/post source
hashes and patches. The Kernel profile keeps the existing interactive limit of
100 candidate tiles per area, adds a validated configurable limit used by the
actual scanner, and retains the five-worker pool. `Integer.MAX_VALUE` means a
larger finite area budget, not additional worker threads. The budget product is
computed as a long to avoid overflow. Existing download, cancellation, retry and
cache-update code remains in use.

Remote/local coverage APIs return detached BitSets; the original fields stay
private. A genuine unique missing-tile count intersects requested cells with
remote coverage and subtracts freshly scanned disk coverage. Overlapping areas
and the international date line are deduplicated. Unknown remote coverage and
invalid geographic bounds throw instead of reporting false completion. Latitude
90 has no tile origin; the northern tile row is 89. Existing filename coverage
is not a validation of DTED (Digital Terrain Elevation Data) sample contents.

The public directory constructor creates an unstarted watcher. The profile scans
it synchronously before use, without adding a polling thread. Missing-count calls
rescan disk; successful downloads retain the genuine `refreshCache` path. The
protected constructor still borrows its supplied watcher and neither starts nor
disposes it. A stable listener reference is retained so dispose removes exactly
the registered listener. The one-shot TAKX count consumer now disposes its task
in a finally block, and calls the count API instead of touching private fields.
Construction and fresh coverage queries scan directories synchronously; callers
should run them away from the user interface thread.

`ElevationDownloadControls.java` exercises the actual patched class: budget
boundaries/overflow, ordinary/date-line/polar/invalid bounds, unique tile counts,
existing/deleted cache filenames, coverage snapshot isolation, invalid limits and
unavailable remote coverage. Its resource fixture is deliberately test-only;
production still uses the real resource manager. It never calls the network
scanner. Both patches apply to exact cached official sources with zero fuzz and
verified postimages. The complete changed downloader family and controls compile
against the accepted public component; 53 actual behavioral assertions pass.
The controls include real date-line, full-world longitude endpoint and polar
coverage, invalid unsorted/raw bounds, and borrowed watcher ownership. Raw invalid
bounds use the protected constructor because the public constructor sorts its
endpoints and can discard a NaN input.

The downloader's genuine error tracker initializes native configuration services.
The passing attempt therefore uses all 36 qualified consumer classpath entries
and freshly extracts the nine unchanged native providers. All 39 mapped executable and
library files match the previously qualified component; 2,746 loaded class origins
are checked. Strict Java Native Interface (JNI) warnings and uncaught callbacks
are zero; three known Simple Logging Facade for Java (SLF4J) notices remain.
Earlier attempts with an incomplete logging classpath and a nonnative extraction
budget remain failed evidence, not acceptance. No shim or new native build was
used to make the tests pass.

Offline control receipt SHA-256:
`0ba9ea26120fc45c9af69d04e5f65e23d38ced9380bfb066ae58d1bda99195a1`.
Independent output, native provider and class-origin audit SHA-256:
`20487fc4081431d0eef4646c077ba4975a9fda6a579026fc706cc5c76e7612e8`.

The complete 1,898-source 5.8 Platform diagnostic has now run with the patched
consumer and all four compiled downloader-family classes. All four elevation
contract errors are gone. The 15 contour and 11 vehicle/Interop errors remain,
with exactly the previous error headers and 50 compiler warnings. No class files
were produced or accepted; the full Platform build still fails.

Full Platform diagnostic receipt SHA-256:
`2050186c524144d442760bf2559cb74e74196bd53284a5a19d686285ad183b49`.
Independent diagnostic/source/classpath audit SHA-256:
`ad6bef0aad542aa4dff17281163d20a6a052cc56410cf87b585a293c5fd750cb`.

The remaining contour and vehicle contracts require real implementations. This
profile does not qualify a client, renderer or network download workflow.

Official local source inventory: the public Kernel revision has no
`gov.tak.api.contour` or `gov.tak.api.vehicle` family. ATAK has 22 actual Android
vehicle-model sources including assets/cache/info, CoT (Cursor on Target) handling
and rendering, plus `ContourLinesOverlay`; these are implementation references,
not drop-in desktop APIs. The local NASA WorldWind source has a real contour
builder and contour lines. TAKX defines its own contour-service consumers and
vehicle CoT adapter. Their Android/resource/coordinate/lifecycle dependencies
must be adapted and tested as genuine project features, not satisfied by names.
