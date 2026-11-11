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
The upgrade chapter resolves its previous release separately from the current
recording's package; the rendered provenance command uses that same resolved
current package URI. Publication defaults stay in the renamed namespace.

For a short edit of existing UI footage without deploying a cluster, use the
[manual UI reel recipe](ui-reel/README.md). It retains historical source hashes
and does not replace published media.
