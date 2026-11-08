# Demo presentation

New demo assemblies use the canonical [TAK on UDS vector artwork](../assets/tak-on-uds-dark.svg) for title cards, endcards and recording watermarks. `style.py` rasterizes that asset with the existing FFmpeg SVG decoder, retaining the artwork's proportions and transparency. It fails if the asset or decoder is unavailable rather than silently substituting a logo. Inter and JetBrains Mono remain required for captions; the logo itself uses vector paths.

The small watermark sits in window chrome, or the phone layout's canvas margin, outside the recorded content. Framed screenshots use the same chrome. Title and endcards link to `github.com/jonathanagustin/uds-takserver`. Generated artwork remains in `demo/out`; it is not a new recording or evidence of a successful deployment.

Render the templates without a cluster, recording or video transcode:

```bash
python3 demo/style.py fonts
python3 demo/style.py branding demo/out/branding
```

This writes `title.png`, `endcard.png`, `frame.png` and `phone.png`. The frame and phone images preview presentation layers without recorded content. Inspect these before running the normal `demo/assemble.sh` pipeline.

Presentation updates do not rewrite historical recordings, release references, signatures, provenance or measured captions. The cast renderer recognizes both the current `uds-takserver` prompt and the legacy prompt so existing captured output remains usable. Reassemble and inspect recordings separately before publishing new videos; this template change does not replace published media.
