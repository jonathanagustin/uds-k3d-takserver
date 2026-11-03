# Docs site

This directory publishes the guides that already live in the repository. It does not keep a second copy of them.

`npm run build` copies `README.md`, the pages in `docs/` listed in `scripts/sync-docs.mjs`, `adr/`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md` into `src/content/docs/`. It adds the frontmatter Starlight needs, rewrites links to the published pages, and then builds. Those copies are gitignored. It drops each page's first `#` heading, because Starlight prints the title itself. A broken link fails the build.

The README's demo players are GitHub `user-attachments` URLs, which only play on github.com. The sync step downloads `demo-deploy.mp4` and `demo-operate-and-trust.mp4` from the `demo` release into `public/demo/`, checks each against the sha256 in `demo-videos.intoto.jsonl`, and turns those README lines into `<video>` players. Pages then serves them as `video/mp4`. The posters in `public/demo/` are committed; the videos are gitignored. In CI a failed download fails the build. A local build without network keeps the download links and warns.

`astro-mermaid` renders the `mermaid` code blocks as diagrams, in the light or dark theme.

```bash
npm ci
npm run build
npm run dev
```

The published site is <https://jonathanagustin.github.io/uds-k3d-takserver/>.
