# Docs site

Starlight site for the markdown already in this repository: `README.md`, `docs/`, `adr/`, and the root guides (`CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`). `npm run build` copies those files into `src/content/docs/` with the frontmatter Starlight needs, rewrites links to the published pages, and then builds. The copies are gitignored.

```bash
npm ci
npm run build
npm run dev
```

The published site is <https://jonathanagustin.github.io/uds-k3d-takserver/>.
