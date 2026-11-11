# Demo presentation

New demo assemblies use the canonical [TAK on UDS vector artwork](../assets/tak-on-uds-dark.svg) for title cards, endcards and large canvas watermarks. The 36px recording title bar uses the matching [Connected stack icon](../assets/tak-mark-dark.svg) at 24px, so its identity survives without miniature lettering. `style.py` rasterizes those assets with the existing FFmpeg SVG decoder, retaining the artwork's proportions and transparency. It fails if the asset or decoder is unavailable rather than silently substituting a logo. Inter and JetBrains Mono remain required for captions; the logo itself uses vector paths.

The small watermark sits in window chrome, or the phone layout's canvas margin, outside the recorded content. Framed screenshots use the same chrome. Title and endcards link to `github.com/jonathanagustin/uds-takserver`. Generated artwork remains in `demo/out`; it is not a new recording or evidence of a successful deployment.

Render the templates without a cluster, recording or video transcode:

```bash
python3 demo/style.py fonts
python3 demo/style.py branding demo/out/branding
```

This writes `title.png`, `endcard.png`, `frame.png` and `phone.png`. The frame and phone images preview presentation layers without recorded content. Inspect these before running the normal `demo/assemble.sh` pipeline.

Presentation updates do not rewrite historical recordings, release references, signatures, provenance or measured captions. The cast renderer recognizes both the current `uds-takserver` prompt and the legacy prompt so existing captured output remains usable. Reassemble and inspect recordings separately before publishing new videos; this template change does not replace published media.

## Selecting application source in CI

The Demo workflow waits for the selected source's immutable TAK, CloudTAK and
PostGIS image indexes and pins their keyed tags before version stamping or
package creation. It does not build missing application images itself.

For an explicit `app_ref`, HEAD moves to that fetched commit while the recorder,
demo tests, workflow file, `tasks.yaml`, `.gitignore` and the shared published-package
resolver remain from the workflow commit. The two recorder branding assets
(`tak-on-uds-dark.svg` and `tak-mark-dark.svg`) and failure diagnostics, including
their redaction helpers, also remain from that commit. Other application assets,
including `assets/icon.svg`, package definitions and image build directories,
remain from the selected application source, as do submodule pins. The producer
lookup uses that fetched SHA; the default PR path keeps the PR head SHA rather than the synthetic merge SHA.

An older ref must contain the supported wait/pin helpers and be compatible with
the current recorder's task defaults. Missing helpers or unsupported read-only wait protocols fail with an explicit
unsupported-source error; this is not universal support for historical release
refs. No plain-tag fallback or replacement source key is used.

Published-release consumers share `.github/scripts/published_package_ref.py`.
Pull requests run a media preflight with a ten-minute job limit. They check the
pinned recording tools, record a short terminal command with VHS, and render and
join short clips through the production media code. They do not deploy a cluster
or record the application walkthroughs.

Start a manual Demo Video run for the full cluster and UI recording. Manual runs
include the upgrade chapter by default; turn off `upgrade` to record only the
main cluster. Publishing and signing remain limited to manual runs from `main`.

The upgrade chapter resolves its previous release separately from the current
recording's package; the rendered provenance command uses that same resolved
current package URI. Publication defaults stay in the renamed namespace.

For a short edit of existing UI footage without deploying a cluster, use the
[manual UI reel recipe](ui-reel/README.md). It retains historical source hashes
and does not replace published media.

## Check media tools before a deployment

The workflow pins the official agg 1.9.0 **MUSL** binary by SHA-256. The GNU
binary for that release requires GLIBC 2.38 and cannot run on Ubuntu 22's
GLIBC 2.35. The same MUSL binary also supports the explicit Ubuntu 24 runner
override.

With the pinned VHS, ttyd, asciinema and agg, plus Chrome, FFmpeg, Pillow, Inter
and JetBrains Mono installed, run:

```sh
python3 demo/tools/check-media.py --output /new/media-preflight
```

This renders a synthetic cast through the cast renderer, assembly sizing filter,
branded window frame and caption filter. It also records a short harmless command
with VHS, using the terminal chapters' settings. The check requires the recorded
command to exit successfully and validates both videos with FFprobe. It joins the
clips through the production crossfade code and renders a synthetic screenshot
through `style.py still`. Videos must use H.264 and yuv420p. The pinned VHS encoder
places its terminal frames over a `lavfi` background stream with FFmpeg's default
rate, producing a 25 fps raw recording. The existing assembly sizing filter applies `fps=30`
before framing. The check requires exactly 25 fps from raw VHS and exactly
30 fps from the framed and joined videos; those outputs must be 1920×1080.

The preflight runs on pull requests and before a manual deployment. A successful
check covers the recorder and short media path. Cluster behavior, browser
walkthroughs and the long final assembly require a full manual recording. Local
protocol tests use explicit fixtures; the real VHS recording must pass on the
hosted runner before merging changes to this check. Existing footage, signatures
and provenance remain unchanged.

Media-tool failures now reveal complete, redacted stderr. Each capture has a
30-minute production deadline, a four-MiB stderr bound, and a 32-MiB
stdout bound for the per-frame metadata that longer recordings produce; incomplete or oversized output
is omitted in full, and the command remains failed. The synthetic preflight uses
a separate 45-second per-command budget and bounded outer CLI calls. A short
preflight does not establish the performance of full recordings. Successful
commands retain their text metadata streams. Failure exceptions remain compatible
with the optional phone-compositor fallback and carry only sanitized stderr;
they do not expose the original command or stdout.
