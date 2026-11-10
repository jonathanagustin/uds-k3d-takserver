<!-- Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only -->

# Community logo concepts

Two original design alternatives for TAK on UDS, prepared for review in
[#411](https://github.com/jonathanagustin/uds-takserver/issues/411). All changes
are contained in this concept directory; the deployed branding is unchanged.

![Community mark comparison, including actual 16, 24 and 32 pixel examples](review-sheet.png)

## Recommendation

**Field unicorn** is the recommended community identity. Its compact horn, ear,
rounded muzzle and broad mane provide a recognizable profile. The unicorn nods
to UDS, while the approachable character suits search and rescue volunteers,
civilian responders, field teams and platform builders. The geometry was drawn
from scratch for this project; it does not use or trace official Defense
Unicorns artwork. The mark expresses project personality rather than a specific
TAK feature, so the full wordmark should introduce it.

**Trail relay** is the operational alternative: a teammate node connects through
a U-shaped route to a navigation arrow. The U ties the field activity to its
platform. This simpler symbol is especially clear at favicon size, but has less
distinctive community character than the unicorn. Neither design depends on a
shield, crosshair or military-only association.

The palette follows the existing project colors: navy `#0F172A` with cyan
`#22D3EE` accents on white, and white `#F8FAFC` with cyan on dark navy `#0B1220`.
An indigo `#4F46E5` accent alternative improves contrast on white. Both designs
retain their structure in one ink.

## Review files

| File | Purpose |
| --- | --- |
| [review-sheet.svg](review-sheet.svg) / [PNG](review-sheet.png) | Editable overview with light, dark, one-ink and native-size examples |
| [wordmark-sheet.svg](wordmark-sheet.svg) / [PNG](wordmark-sheet.png) | Both concepts paired with the existing outlined project lettering |
| [index.html](index.html) | Responsive local review page; open directly in a browser |
| `field-unicorn-{light,dark,mono,indigo}.svg` | Standalone 64-unit unicorn marks |
| `trail-relay-{light,dark,mono,indigo}.svg` | Standalone 64-unit relay marks |
| `*-wordmark-{light,dark}.svg` | Complete 770 × 192 vector wordmarks |
| `favicon-proof/*-{16,24,32}.png` | 24 transparent exports at exact favicon dimensions |
| [build-preview.py](build-preview.py) | Hand-authored geometry and reproducible SVG/HTML assembly |

![Existing project lettering with the alternative marks](wordmark-sheet.png)

## Small-size behavior

The same silhouette is used at 16, 24 and 32 pixels. At 16 pixels, the unicorn's
5-unit eye renders at about 1.25 pixels and should be treated as incidental. Its
horn, muzzle, neck and mane carry recognition. The relay's 10-unit route renders
at 2.5 pixels, giving it a more stable small-size stroke; its node and arrow remain
distinguishable in one ink. Antialiasing varies by renderer, so final adoption
should include an actual browser-tab check on the chosen light/dark favicon.

Use the light SVG on light surfaces and the dark SVG on dark surfaces. For a
16-pixel favicon on a light browser tab, prefer the indigo or mono variant: cyan
has lower contrast against white, especially at the horn and arrow tips. The mono
SVG uses `currentColor`: when embedded inline, set CSS `color` to the desired
ink. A standalone SVG loaded with `<img>` defaults to black; set its colors in
the SVG itself for a white standalone asset. The marks have transparent
backgrounds. Minimum clear space for use alongside other content is 8 units
(one eighth of the 64-unit view box) outside the view box.

The production mark and wordmark files use only SVG paths, circles and groups,
plus accessible titles/descriptions. Their lettering is outlined, so they have
no font dependency, external references, embedded raster images, script, filters,
gradients or shadows. The review sheets use ordinary text for annotations.

## Rebuild and validation

Run `python3 build-preview.py` from this directory to rebuild the SVGs and HTML.
For a proof PNG, use Inkscape, for example:

```sh
inkscape review-sheet.svg --export-type=png --export-filename=review-sheet.png
inkscape field-unicorn-light.svg --export-width=16 --export-type=png \
  --export-filename=favicon-proof/field-unicorn-light-16.png
```

The review sheets and standalone marks were rendered with Inkscape and visually
inspected. Every SVG parsed as XML; mark/wordmark files were checked for accessible
titles, external references and embedded/raster/script content. All 24 favicon
PNGs have their specified dimensions. A headless Chromium screenshot attempt
stalled in the shared environment; the supplied PNG review sheets are direct SVG
renders, not browser screenshots.
