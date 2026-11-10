# UI reel preview

Make a 26-second, silent 1080p reel from the project's existing public demo
footage. It shows CloudTAK mapping, marker creation, feature sharing and the
TAK Server status page. This is an edit of historical recordings, not a new
deployment recording or a TAKX demo.

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
artifact. It starts no cluster, builds no application images, and publishes no
release assets. After downloading and extracting its artifact, verify both
subjects using GitHub CLI:

```sh
gh attestation verify uds-takserver-ui-preview.mp4 \
  --repo jonathanagustin/uds-takserver \
  --signer-workflow jonathanagustin/uds-takserver/.github/workflows/ui-reel.yaml
gh attestation verify edit-manifest.json \
  --repo jonathanagustin/uds-takserver \
  --signer-workflow jonathanagustin/uds-takserver/.github/workflows/ui-reel.yaml
```

Local renders have no workflow attestation. Publishing or replacing release
media remains a separate reviewed step; this recipe does not alter the existing
deployment/demo recording workflow.

Run the bounded acquisition fixtures without downloading footage or rendering:

```sh
python3 -m unittest discover -s demo/ui-reel -p test_render.py
```
