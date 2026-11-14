# Joined Kernel spatial database profile

The pinned libxml2 archive is an ordinary Git blob, so its download uses the
official raw-content endpoint. The media/LFS endpoint returns 404 for that file.
Its revision, archive size, hash and extracted-source contract are unchanged.

This opt-in Linux amd64 experiment compiles unchanged official Kernel legacy database, Port and pthread translation units. It joins real Spatialite 4.3.0a, libiconv 1.15 and libxml2 2.13.3 with receipt-verified GEOS, PROJ and SQLCipher/OpenSSL and zlib prefixes. It preserves TTP-enabled GEOS, PROJ, iconv and XML features and the genuine 1024-connection cache generator.

The consumer must pass actual Kernel SQL geometry/coordinate conversion, prepared typed rows, commit/rollback and reopen checks. This is not modern Database2 encrypted-open, GDAL/ZIP, full SDK, JNI, renderer, target ABI, security or TAKX client acceptance. The legacy API has no explicit key argument; using SQLCipher as its engine does not establish encrypted-open behavior.

The original Spatialite patch has one context mismatch: config.sub's unchanged `d10v` line includes `dvp` in the patch but not in the official archive. The recipe verifies the original patch hash, changes only that unique context line, verifies the normalized patch hash and unchanged semantic additions/deletions, then applies with zero fuzz. Every changed source pre/postimage is pinned. The original preparation failure remains separate evidence; no geometry code or feature is removed by normalization.

Run with verified existing component outputs (no leaf rebuilds):

```sh
python3 takx/kernel-spatial-db/build.py --source /official/pinned/atak-civ --output /private/new-output --cache /private/source-cache --proj-proof /verified/proj --geos-proof /verified/geos --sqlcipher-proof /verified/sqlcipher --zlib-proof /verified/assimp-zlib
```

Sources are offline by default; `--fetch-dependencies` permits the exact locked official archives/patches. One compiler job, a 30-minute command deadline and between-command 4 GiB output/cache checks bound the experiment. They are not kernel-enforced memory/disk quotas. Output/logs remain private. A failure stops without a success receipt; source compatibility changes and retries require separate review.

Run offline guards with `python3 -B -m unittest discover -s takx/kernel-spatial-db -p test_build.py -v`. No default test compiles source or fetches dependencies.

The first completed source build exposed missing real Kernel Blob/Logging translation
units and Spatialite compression dependencies at the final link. The corrected
profile includes those whole upstream units and reuses verified source-built
zlib 1.3.1 from the Assimp receipt, without a leaf rebuild. Its headers and archive
are explicitly selected. libiconv.a already contains locale_charset; its sibling
libcharset.a remains installed and hash-verified but is not forced into the same
whole-archive link, avoiding duplicate genuine provider definitions. Original
failed output and its frozen commit remain separate evidence.

A later real consumer passed, but strict whole-archive linking exposed nested
archives created by passing absolute third-party archives through legacy
libtool metadata. Configure metadata now uses ordinary private-prefix library
flags; final consumer and PIC links still select exact real archives. A binary
archive guard rejects nested archives and non-ELF relocatable members. This
changes packaging metadata, not upstream source features or algorithms.

For a completed local receipt, run the same guard command with
`TAKX_KERNEL_SPATIAL_DB_PROOF=/private/completed-output` to verify its bound
artifacts/providers and replay the real Kernel consumer with a new owned database.
This executes the verified consumer only; it does not rebuild dependencies.

Provider reuse validates the current owned producer recipe and its pinned
source/archive/version/positive scope, then actual source, installed, tool and
runtime inventories. Complete receipt bytes are not a machine-specific golden
input: whitespace and production-path metadata can differ between valid local
builds. Each actual input receipt SHA remains recorded in the integration output
for traceability. These unsigned local checks establish cache integrity, not
publisher authentication or permission to trust arbitrary third-party receipts.
