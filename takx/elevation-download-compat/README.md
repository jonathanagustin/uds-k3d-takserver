# TAKX 5.8 elevation-download compatibility source profile

Local source candidate, not compiler/runtime acceptance. The new public Kernel
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

`ElevationDownloadControls.java` exercises the actual patched class: budget
boundaries/overflow, ordinary/date-line/polar/invalid bounds, unique tile counts,
existing/deleted cache filenames, coverage snapshot isolation, invalid limits and
unavailable remote coverage. Its resource fixture is deliberately test-only;
production still uses the real resource manager. It never calls the network
scanner. These controls have NOT been compiled or executed. Both patches were
applied to exact cached official sources with zero fuzz and verified postimages;
that is source preparation only.

Next, after root review and an exclusive Java slot: compile the complete changed
ElevationDownloader source family against the accepted component, compile/run
these offline controls with bounded output and core dumps disabled, then rerun
all 1,898 genuine 5.8 Platform sources using only the two reviewed postimages and
complete changed family. Preserve all remaining contour/vehicle diagnostics;
never accept partial Platform classes. No native rebuild is needed for this
family. This does not qualify a client, renderer or network download workflow.

Official local source inventory: the public Kernel revision has no
`gov.tak.api.contour` or `gov.tak.api.vehicle` family. ATAK has 22 actual Android
vehicle-model sources including assets/cache/info, CoT (Cursor on Target) handling
and rendering, plus `ContourLinesOverlay`; these are implementation references,
not drop-in desktop APIs. The local NASA WorldWind source has a real contour
builder and contour lines. TAKX defines its own contour-service consumers and
vehicle CoT adapter. Their Android/resource/coordinate/lifecycle dependencies
must be adapted and tested as genuine project features, not satisfied by names.
