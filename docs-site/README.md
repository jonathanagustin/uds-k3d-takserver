# Docs site

This directory publishes the guides that already live in the repository. It does not keep a second copy of them.

`npm run build` copies `README.md`, `docs/`, `adr/`, `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md` into `src/content/docs/`. It adds the frontmatter Starlight needs, rewrites links to the published pages, and then builds. Those copies are gitignored. A broken link fails the build.

```bash
npm ci
npm run build
npm run dev
```

The published site is <https://jonathanagustin.github.io/uds-k3d-takserver/>.
