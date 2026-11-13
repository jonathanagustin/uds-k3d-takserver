<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Field mark

Selected direction B: a single black or white interlocking T/U monogram with an angled T cap and chamfered U base. The 96-unit master is shared by the canonical icons, wordmarks, documentation favicon, social card and future demo assemblies. Use black on light surfaces and white on dark surfaces; preserve the clear gaps and the artwork's proportions.

The lockup reads **TAK Server** with smaller **on UDS** beneath. All lettering is outlined vector artwork using the installed Liberation Sans Bold and Regular fonts, licensed under SIL OFL 1.1. Font attribution: digitized data copyright 2010 Google Corporation; copyright 2012 Red Hat, Inc. No font binaries are included. The OFL's document exception applies to the rendered lettering. See [Liberation Fonts](https://github.com/liberationfonts/liberation-fonts) for the font source and license.

`/usr/bin/python3 assets/fieldmark/build.py` regenerates the canonical SVGs, 1200×630 `docs-site/public/og.png`, this preview, and transparent 16/24/32 px light/dark favicon PNG proofs. It requires existing system fontTools, Liberation Sans and Inkscape; it installs nothing.

[Preview](preview.png) includes both themes and the favicon marks at their actual intended sizes. The theme-aware canonical favicon uses the same geometry. Existing README, docs navigation/hero and demo renderers reference the canonical assets directly.

Historical concept boards, published demo media, locked inputs and manifests are retained as evidence of their original renders. New demo renders use the current canonical assets. The social card is ready to upload to GitHub's repository social-preview setting; that owner setting is separate from the documentation site's Open Graph image.
