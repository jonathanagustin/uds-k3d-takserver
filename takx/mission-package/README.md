# Mission-package conformance and bounded admission

This lane exercises real official TAKX reader/JAXB serializer code, then an
explicit owned admission patch to that same production path. It does not emulate
an Android importer or claim an end-to-end CommonCommo transfer.

## Synthetic client fixture

```sh
python3 takx/mission-package/build_fixture.py --output /fresh/synthetic.dpk
```

The deterministic stored ZIP contains `MANIFEST/manifest.xml`,
`cot/synthetic-android-mission-point.cot` and `files/README.txt`. It has manifest
version 2, package UUID `00000000-0000-4000-8000-000000000410`, CoT UID
`synthetic-android-mission-point`, label **SYNTHETIC-MISSION TEST** and point 0,0.
Receive-import is true and receive-delete false. Fixed synthetic timestamps,
including the future stale date, are not live tracking. No real captures, people
or operational coordinates are copied. Changed fixture bytes and existing output
paths are refused.

Canonical package SHA-256:
`584c217da05781b6c20e71683e893db1e9de4f907243f4c79f643a28623936d6`.
The Android scenario can hash-bind this package and stage it for manual import;
offline validation or staging is not import/map-display success.

## Actual-source profiles

`inputs.lock.json` pins official TAKX 5.7 revision
`0b59a9bb2d0e90dc35c9edfff1c2056daab2b713`, eleven real reader/model dependency
sources and nine external cached JARs. `admission-profile.json` separately binds
four actual pre/postimages and patch lineage: Platform `ZipReader`,
`PackageReader`, `PackageImporter`, and Client `DataPackageManager`.

Export without modifying official sources or compiling:

```sh
python3 takx/client-compiler/build.py \
  --mission-admission-source /verified/TAKX-checkout \
  --mission-admission-export /fresh/source-projection
```

The projection includes only the four checked postimages and a receipt. It is
not a Platform or Client artifact. Existing baseline locks and class providers
remain unchanged. The v1 three-source profile and patch are retained under
`profiles/` and `patches/`; previous qualification receipts are not relabeled.

The v2 Linux desktop profile bounds admission and extraction after download.
It does not cap network-download bytes before CommonCommo completion.

The profile:

- Caps archive/aggregate bytes at 256 MiB, each entry at 64 MiB, inventory at
  2,048 entries and manifest at 1 MiB. It preserves ordinary directory records.
- Rejects duplicate, traversal, absolute, backslash, drive, dot/empty/control
  path segments and file/directory collisions. Bounded streams check declared
  size and CRC; the actual JAXB manifest parser explicitly rejects DTD/external
  entities and validates nonignored content references. Ignored absent content
  and actual serializer/legacy-root behavior remain supported.
- Requires the remote callback's documented 64-hex SHA-256, verifies actual file
  bytes and drains all regular ZIP streams before notifications/import. Missing
  pending state, hash mismatch and read/admission errors stop the callback.
  Manual/local entry points do not gain a remote-hash requirement.
- Routes extra-certificate reads through bounded streams without changing which
  certificates the existing importer selects. This does **not** solve certificate
  authorization or trust policy. A matching sender-supplied SHA is not proof of
  sender identity or a signed/authenticated package.
- Uses actual archive SHA plus exact entry-path SHA for extraction-cache identity,
  retaining the original basename. Checked same-directory staging and exclusive
  hardlink completion prevent arbitrary overwrite; unsupported filesystems fail
  closed. Identical cached bytes are verified; stale archives, same basenames,
  symlinks, corrupt cache entries and partial stages cannot reuse the old flat
  cache. This is a Linux project profile, not a claim for every filesystem.

## Offline qualification

Use existing sources/JARs; the runner never downloads, clones, runs Gradle or
builds native code:

```sh
python3 takx/mission-package/qualify.py \
  --takx-source /verified/TAKX-checkout \
  --maven-root /verified/cached-jars --java-home /verified/jdk-17 \
  --admission-projection /fresh/source-projection \
  --output /fresh/qualification
```

Omit `--admission-projection` for the unchanged baseline characterization. Actual
`getManifest`, `readEntry`, `toXml`, shared remote admission and extraction
methods run; no substitute parser or SDK behavior stubs are supplied. The tiny
build uses a 128 MiB heap, controls 64 MiB, 45-second deadlines and 64 KiB per-file
command limits. Fresh receipts retain code/tool/source/output hashes; failures
keep their own output directories.

The baseline qualified 18 assertions while honestly recording missing admission
guards. The patched v2 qualified 49 real checks, including round trips, ignored
metadata, directories, malformed XML, DTDs, ZIP limits/CRC/path inventory, remote
hash/read failures, cache collisions/staleness/symlinks, cleanup and concurrent
identical extraction. Large-size metadata negatives use tiny controlled headers;
no decompression bomb is run. Android's nested-wrapper manifest is unsupported
by this TAKX reader and remains rejected.

A genuine full Platform rebuild compiled 1,815 source inputs into 2,099 classes
and 17 generated sources. A separate full Client compile consumed that artifact,
removed the old Platform provider and compiled all 1,678 Client sources into
2,815 classes plus its generated EventBus source, with zero errors. That Client
receipt binds recipe SHA
`e4eb9c4ed924f00e0e8bf2d9ac62b615aa1c5c3a13d2a8674c9fed9f04fd7b88`,
profile SHA `28fdd12398445d8b60d9ebc2a47c926f2b5837f44a7333b0b7e1636a6401f966`
and genuine Platform receipt SHA
`372810c164f15665b64f1b5569512f39aff9dfbcc515b8bd229261acf82d115c`.
Client receipt SHA:
`d41cb5b7fe4d0779df8864347311e8f92aa39ffeac885671f24a5d9d5452f84b`.

These are compile-only and bounded-reader evidence. Full CDI/UI receive/import,
actual server/client transfer, native feature runtime and full Gradle acceptance
remain separate gates. The eleven selected reader/model files are byte-identical
in the cached 5.8 revision recorded in the lock; this does not qualify full 5.8.

Lightweight hosted guards:

```sh
python3 -m unittest discover -s takx/mission-package -p 'test_*.py'
python3 -m unittest discover -s takx/client-compiler -p 'test_*.py'
```

## Provenance and distribution

Synthetic files are original project data. Their shape follows official ATAK-CIV
`MissionPackageManifest`, configuration/content, builder and extractor semantics
at `9f6893dd657feacc35ec5de03dad721c2e44170e`; the lock retains exact source hashes
and Git blob IDs. Relevant CommonCommo receive-contract and actual TAKX caller
hashes are retained too. Public source uses GPLv3 and applicable per-file notices;
external JAXB/Jakarta/SLF4J/Commons JARs retain their own licenses and are not
redistributed here. Pinned versions reproduce this qualification, not a blanket
runtime dependency recommendation.
