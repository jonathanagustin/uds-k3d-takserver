<!-- Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only -->

# Community logo concepts

Two original design alternatives for TAK on the **Unified Defense Stack (UDS)**,
prepared for review in [#411](https://github.com/jonathanagustin/uds-takserver/issues/411).
The brief connects an integrated platform to TAK's shared situational awareness
for search and rescue, civilian response and other field teams. All changes are
contained in this concept directory; deployed branding is unchanged.

![Platform mark comparison, including actual 16, 24 and 32 pixel examples](review-sheet.png)

## Directions

**Relay stack** is the literal platform alternative. Three substantial service
layers share a single relay, ending in a navigation heading. It connects the
Unified Defense Stack's integrated platform to TAK's field purpose. The mark
remains compact without miniature server ports, map grids or lettering.

**Unified route** is the recommended identity, particularly for favicons. A teammate node connects
through a U-shaped route to a navigation heading. This expresses shared field
awareness with fewer elements, while the accompanying wordmark provides the
platform context. Its U also offers a simple mnemonic for Unified Defense Stack.

Both use original geometry drawn for this project. The palette follows the
existing project colors: navy `#0F172A` with cyan `#22D3EE` accents on white,
and white `#F8FAFC` with cyan on dark navy `#0B1220`. An indigo `#4F46E5`
accent alternative improves contrast on white. Both retain their structure in
one ink.

## Review files

| File | Purpose |
| --- | --- |
| [review-sheet.svg](review-sheet.svg) / [PNG](review-sheet.png) | Editable overview with light, dark, one-ink and native-size examples |
| [wordmark-sheet.svg](wordmark-sheet.svg) / [PNG](wordmark-sheet.png) | Both concepts paired with the existing outlined project lettering |
| [index.html](index.html) | Responsive local review page; open directly in a browser |
| `stack-relay-{light,dark,mono,indigo}.svg` | Standalone 64-unit Relay stack marks |
| `trail-relay-{light,dark,mono,indigo}.svg` | Standalone 64-unit Unified route marks |
| `*-wordmark-{light,dark}.svg` | Complete 770 × 192 vector wordmarks |
| `favicon-proof/*-{16,24,32}.png` | 24 transparent exports at exact favicon dimensions |
| [build-preview.py](build-preview.py) | Hand-authored geometry and reproducible SVG/HTML assembly |

![Existing project lettering with the alternative platform marks](wordmark-sheet.png)

## Small-size behavior

The same silhouette is used at 16, 24 and 32 pixels. At 16 pixels, the Relay
stack's 10-unit layers render at 2.5 pixels, with 1.5-pixel gaps. Its connecting
bus is 2 pixels wide. The Unified route's 10-unit path renders at 2.5 pixels;
its node and arrow remain distinguishable in one ink. Antialiasing varies by
renderer, so final adoption should include an actual browser-tab check on the
chosen light/dark favicon.

Use the light SVG on light surfaces and the dark SVG on dark surfaces. For a
16-pixel favicon on a light browser tab, prefer the indigo or mono variant: cyan
has lower contrast against white, especially at the arrow tips. The mono SVG
uses `currentColor`: when embedded inline, set CSS `color` to the desired ink.
A standalone SVG loaded with `<img>` defaults to black; set its colors in the
SVG itself for a white standalone asset. The marks have transparent backgrounds.
Minimum clear space for use alongside other content is 8 units (one eighth of
the 64-unit view box) outside the view box.

The production mark and wordmark files use SVG paths, rectangles, circles and
groups, plus accessible titles/descriptions. Their lettering is outlined, so
they have no font dependency, external references, embedded raster images,
script, filters, gradients or shadows. Review sheets use ordinary text for
annotations.

## Rebuild and validation

Run `python3 build-preview.py` from this directory to rebuild SVGs and HTML.
For a proof PNG, use Inkscape, for example:

```sh
inkscape review-sheet.svg --export-type=png --export-filename=review-sheet.png
inkscape stack-relay-indigo.svg --export-width=16 --export-type=png \
  --export-filename=favicon-proof/stack-relay-indigo-16.png
```

The review sheets and standalone marks were rendered with Inkscape and visually
inspected. Every SVG parsed as XML; mark/wordmark files were checked for accessible
titles, external references and embedded/raster/script content. All 24 favicon
PNGs have their specified dimensions. A headless Chromium screenshot attempt
stalled in the shared environment; supplied PNG review sheets are direct SVG
renders, not browser screenshots.
