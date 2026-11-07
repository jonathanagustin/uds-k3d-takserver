# Docs site

This directory publishes the guides that already live in the repository. It does not keep a second copy of them.

`npm run build` builds release documentation and the current checkout together.
The site root contains the newest stable release. `/main/` contains unreleased
documentation and displays a banner. Up to five release minors are retained,
using only the newest patch per minor from v0.7 onward; older minors use paths
such as `/v0-8/`. Pre-release and non-version tags are excluded.

`scripts/build-versions.mjs` creates temporary detached worktrees for the release
tags, runs the current `scripts/sync-docs.mjs` against each source tree, and removes
the worktrees afterward. Fetch all tags before building (`git fetch --tags`).
The sync script accepts `--repo-root`, `--output-root`, `--url-prefix`, `--git-ref`,
and `--source-ref`. It copies README, the existing `docs/` reference pages,
`docs/how-to/` when present, `adr/`, and the repository policy/changelog files.
Only files present in that version are included. Generated content and version
metadata are gitignored. A broken internal link fails the build.

Internal document links and sidebars stay inside the selected version. Released
pages link to `blob/<tag>/` for their sources; main links to `edit/main/`.
Last-updated dates are read from the corresponding ref's history. The version
selector retains the current page when it exists in the destination version and
otherwise opens that version's home. Pagefind indexes each page with a version
filter, and the search dialog locks queries to the currently selected version.

The Docs workflow builds on main pushes and published releases. Release events
use the main renderer and fetch all tags, so publishing a release moves the
latest documentation to the root without copying snapshots into the repository.

When a source ref contains `src/home.mdx`, it provides that channel's splash page.
An older release without this file receives a small navigation shell pointing to
its own guides. README is published at Getting started. On an authored splash,
a home URL hash such as `/#quick-start` opens that section on Getting started.
The header logo is `assets/icon.svg`; `public/favicon.svg` is the same mark.
`public/og.png` is the static social image.

`starlight-llms-txt` writes `/llms.txt`, `/llms-full.txt`, and `/llms-small.txt` during the build.

`npm test` runs Playwright against `npm run preview`; build first. The checks
cover version switching, absent-page fallback, search isolation in every
channel, the theme toggle, 404 handling, Mermaid, code titles, `llms.txt`, and
demo players. Current-feature checks use `/main/`, so a release without a new
feature does not accidentally inherit it. Video checks send `HEAD`, inspect the
status/type/length, and do not download the file. Install Chromium once with
`npx playwright install chromium`. `DOCS_PREVIEW_PORT` can select another local
port when multiple worktrees are being tested.

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
