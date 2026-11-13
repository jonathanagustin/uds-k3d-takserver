# UI reel preview

Make a 26-second, silent 1080p reel from the project's existing public demo
footage. It shows CloudTAK mapping, marker creation, feature sharing and the
TAK Server status page. This is an edit of historical recordings, not a new
deployment recording or a TAKX demo.

The [published v0.12.0 preview](https://github.com/jonathanagustin/uds-takserver/releases/download/v0.12.0/uds-takserver-ui-preview.mp4)
reuses the reviewed render without changing its bytes. Its
[source manifest](https://github.com/jonathanagustin/uds-takserver/releases/download/v0.12.0/edit-manifest.json)
retains the historical input identities; publication is not a fresh capture.

Run with Python 3.11 or later and FFmpeg/FFprobe with `libx264` and `drawtext`:

```sh
python3 demo/ui-reel/render.py
```

The default output is `demo/out/ui-reel/`. Inspect `review-strip.jpg` and the
video before sharing. Use a new empty output directory for each edit. To reuse
previously downloaded inputs without network access:

```sh
python3 demo/ui-reel/render.py --offline --output demo/out/ui-reel-review
```

`inputs.lock.json` records the exact source asset IDs, release, URLs, original
update times and SHA-256 digests. It also pins the official Inter 4.1 font
archive, whose SIL Open Font License is copied into the output. A changed
download or cached input fails verification before FFmpeg starts; a moving
`demo` release cannot silently replace the locked recordings. If those old
assets are no longer available, restore the matching bytes into the cache
instead of changing hashes merely to make the edit run.

The manifest records the input lock, scene timings, editor hash, FFmpeg versions,
output hashes and media probe. Font and footage bytes are locked; encoded video
bytes may differ across FFmpeg builds. The output keeps a visible recorded
footage label. Original release signatures do not sign the edited output and
are not copied onto it.

The manual **UI reel preview** workflow runs only on `main`, creates a GitHub
provenance attestation for the video and manifest, and uploads a 14-day review
artifact when both optional inputs are empty. It starts no cluster and builds
no application images. After downloading and extracting its artifact, verify
both subjects using a current GitHub CLI:

```sh
gh attestation verify uds-takserver-ui-preview.mp4 \
  --bundle attestation.sigstore.json \
  --repo jonathanagustin/uds-takserver \
  --signer-workflow jonathanagustin/uds-takserver/.github/workflows/ui-reel.yaml
gh attestation verify edit-manifest.json \
  --bundle attestation.sigstore.json \
  --repo jonathanagustin/uds-takserver \
  --signer-workflow jonathanagustin/uds-takserver/.github/workflows/ui-reel.yaml
```

Local renders have no workflow attestation. This recipe does not alter the
existing deployment/demo recording workflow.

## Publish an existing signed preview

After reviewing a successful render, manually dispatch **UI reel preview** on
`main` with both `release_tag` (for example, `v0.12.0`) and `source_run_id` (the
render run's positive numeric ID). The target must already be a published,
nondraft, non-prerelease stable release. Mixed inputs, prerelease tags and
non-main dispatches fail. Publication reuses the original six artifact files;
it does not rerender footage or create a release.

The separate publisher has `contents: write` and `actions: read`. The renderer
retains read access plus attestation/OIDC permissions. Publish jobs queue in a
separate FIFO concurrency group and never cancel active uploads. The publisher
uses GitHub CLI 2.103.3, with its official Linux archive SHA-256 pinned in the
workflow; a changed archive fails before execution.

Before any release write, `publish.py` checks all of the following:

- The completed, successful source is a manual `ui-reel.yaml` run on `main` in
  this repository, with matching repository IDs, workflow ID and commit.
- Its sole `ui-reel-preview` artifact is unexpired and matches the API archive
  digest, size and source identity. The archive contains exactly the video,
  poster, review strip, edit manifest, Sigstore bundle and Inter license, with
  no extra paths or symlinks. Compressed and expanded sizes are bounded at
  64 MiB; each GitHub command times out after 120 seconds, within a 15-minute job.
- The manifest matches all four media/license output hashes and sizes. Real
  `gh attestation verify --bundle` verifies both video and manifest with the
  repository, exact workflow signer, signer/source commit, main ref and GitHub
  OIDC issuer pinned. The verified SLSA statement must also match the repository
  and owner IDs, source workflow, event and exact source run **attempt**. Merely
  decoding the unsigned bundle payload is insufficient.
- Existing assets with any of the six fixed names must have the same API
  SHA-256 digest and size. A missing digest, collision or conflicting preview
  section fails before uploads; no asset is overwritten or deleted.

Each missing file is uploaded with its original bytes and filename, then its
API SHA-256 digest and size are checked. Interrupted publication can be retried:
matching files are retained, missing files are added, and a marked preview
section is appended once after all six assets are confirmed. Existing release
notes are preserved. The section identifies an edit of previously recorded
CloudTAK mapping and TAK Server administration footage. Publication is not a
multi-file transaction: an interrupted attempt may leave a verified
subset, which the same-input retry completes. The workflow serializes its own
publishers; avoid concurrent manual edits to the same release notes/assets.

The signed original artifact and bundle remain the provenance record; the
publisher creates no replacement attestation. Expired artifacts must be
rendered and reviewed again rather than recovered from an unverified source.

Run the bounded acquisition fixtures without downloading footage or rendering:

```sh
python3 -m unittest discover -s demo/ui-reel -p test_render.py
```

Run offline publisher fixtures (no downloads, rendering or release writes):

```sh
uv run --no-project --with pyyaml==6.0.3 python -B -m unittest discover -s demo/ui-reel -p test_publish.py -v
```


## Optional historical scene review exports

Pass `--export-scenes` to also create a separate sibling directory (by default
`demo/out/ui-reel-scenes/`). The existing reel output stays unchanged. Only three
existing scenes meet the 5–10 second clip brief: `create-map-marker` (6 seconds),
`share-feature` (6.5 seconds) and `shared-marker` (6 seconds). They reuse the
already encoded scenes, including the visible recorded-footage caption. No
footage is extended, looped or relabeled as a new capture.

Each clip has a poster and individual JSON manifest binding the exact locked
source asset and interval, font input, recipe/lock hashes, tool versions, clip
and poster hashes/sizes and measured media properties. The font license is
included. These records do not invent missing original capture-run or application
version metadata. Offline fixture tests prove wiring and hash contracts, not
visual quality; inspect every real clip and poster before sharing.

The manual workflow's `export_scenes` input defaults to false. When enabled it
attests all three clip MP4s and individual manifests and retains the bundle in a
separate `ui-scene-previews` review artifact. Verify each MP4 and JSON with the
same repository/workflow signer flags shown above and that artifact's bundle;
check each poster against its verified manifest. Local exports are unsigned.
Scene export cannot be combined with release publication. The existing strict
six-file reel publisher does not accept scene artifacts. Publishing clips,
vertical reframing, new scenes and fresh deployment/interoperability evidence
remain separate work.

Future renders use the canonical Field mark wordmark from
`assets/tak-on-uds-dark.svg` in the upper canvas margin. New edit manifests record
its SHA-256 alongside the original footage and font inputs. Existing videos,
posters and their provenance records are not regenerated by a branding change.

## Immutable historical scene publication

The manual **UI reel preview** workflow accepts `scene_source_run_id` and
`scene_source_attempt` to publish an existing `ui-scene-previews` artifact.
Leave `release_tag`, `source_run_id` and `export_scenes` empty or false for this
mode. It neither renders nor signs media and does not start a cluster. The
combined-reel publisher keeps its separate, unchanged six-file contract.

Publication requires a committed review record at
`demo/ui-reel/reviews/<run>-<attempt>.json` in the publisher checkout. There is
**no completed review record for run 42940218710**: its 555-frame privacy review
remains open. Posters and periodic samples do not establish a complete review.
Inspect every frame at readable resolution, including transient notifications,
cuts and fades; check synthetic locations and identities, legibility, metadata,
and absence of credentials or operational data. Record the review only after it
is complete.

A review record has exactly these fields:

| Field | Required value |
| --- | --- |
| `schema` | Integer `1` |
| `source_run_id`, `source_attempt`, `source_commit` | Exact producing run, attempt and 40-character commit |
| `reviewer`, `reviewed_at` | Reviewer GitHub handle and completed review time as `YYYY-MM-DDTHH:MM:SSZ` |
| `full_frame_privacy_review` | Boolean `true` after the complete review |
| `frames` | `create-map-marker.mp4: 180`, `share-feature.mp4: 195`, `shared-marker.mp4: 180` |
| `sha256` | Exact filename-to-SHA-256 mapping for all eleven original artifact files |

The eleven files are three MP4 clips, their three JPG posters, their three JSON
scene manifests, `Inter-LICENSE.txt` and `attestation.sigstore.json`. Six MP4/JSON
subjects must pass cryptographic provenance verification; each signed JSON
manifest binds its poster. The publisher also checks the source recipe and lock,
font license, actual silent 1080p/30fps media, complete frame counts and the exact
reviewed hashes. Review records are read from Git, never from the downloaded
artifact. Untracked approval files cannot authorize publication.

The target is always `ui-scenes-run-<run>-attempt-<attempt>`, a prerelease at the
producer commit, excluded from the latest package release. The publisher stages
a draft, uploads original bytes without overwriting, reads every asset back by
immutable ID, and only then makes it public. A retry may add missing matching
assets to the draft; a mismatch stops publication. A complete matching public
release is verified without edits. Keep the historical `demo` release and
`inputs.lock.json` unchanged. README and documentation links should select the
new release explicitly after verified publication.

These files remain historical CloudTAK/ATAK edits. Their original captions and
branding are preserved. They do not establish current deployment, new branding,
TAKX interoperability, sign-in, Grafana or Portal acceptance, or measured delivery
latency. The create-marker clip ends at the Create Point action without showing
the completed result. Publication alone does not complete issue #410.
