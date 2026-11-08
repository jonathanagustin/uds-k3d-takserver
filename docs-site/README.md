# Docs site

This directory publishes the guides that already live in the repository. It does not keep a second copy of them.

`npm run build` copies `README.md`, the pages in `docs/` listed in `scripts/sync-docs.mjs`, `adr/`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md` into `src/content/docs/`. It adds the frontmatter Starlight needs, rewrites links to the published pages, and then builds. Those copies are gitignored. It drops each page's first `#` heading, because Starlight prints the title itself. A broken link fails the build.

`src/home.mdx` is copied to the site home. It is a short page of cards. The README is published at Getting started, not at the home URL. A hash on the home URL, such as `/#quick-start`, opens that section on Getting started. The header logo is `assets/icon.svg`. `public/favicon.svg` is the same mark and was already served as the favicon. `public/og.png` is the static social image.

`starlight-llms-txt` writes `/llms.txt`, `/llms-full.txt`, and `/llms-small.txt` during the build.

`npm test` runs the Playwright checks against `npm run preview`. Run the build first. The checks cover the theme toggle, the 404 page, Mermaid labels, code block titles, `llms.txt`, and the demo players. A video check sends `HEAD` and reads the status, content type, and content length. It does not download the file. The build still copies the videos from the `demo` release, as below. Install the browser once with `npx playwright install chromium`.

Text between `<!-- github-only:start -->` and `<!-- github-only:end -->` stays on GitHub and is left off the site. The README uses it for the line that points readers to this site. A link whose text is a file path, like `[docs/sso.md](docs/sso.md)`, shows the page title on the site instead, such as `Single sign-on`.

The README's demo players are GitHub `user-attachments` URLs, which only play on github.com. The sync step downloads `demo-deploy.mp4` and `demo-operate-and-trust.mp4` from the `demo` release into `public/demo/`. It checks each file against the sha256 in `demo-videos.intoto.jsonl`. Then it turns those README lines into `<video>` players.

Pages then serves them as `video/mp4`. The posters in `public/demo/` are committed; the videos are gitignored. In CI a failed download fails the build. A local build without network keeps the download links and warns.

`astro-mermaid` renders the `mermaid` code blocks as diagrams, in the light or dark theme. Those diagrams set `htmlLabels` to false and do not use `<br>` or angle brackets. With HTML labels on, GitHub strips the label markup and the boxes draw empty.

```bash
npm ci
npm run build
npx playwright install chromium
npm test
npm run dev
```

The published site is <https://jonathanagustin.github.io/uds-k3d-takserver/>.
