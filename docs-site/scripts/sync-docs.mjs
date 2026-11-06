// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Copies the repository markdown into src/content/docs with the frontmatter
// Starlight requires, and points links at the published page or at GitHub.
// The copies are gitignored. The files in the repository stay the source.

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, statSync } from 'node:fs';
import { mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '../..');
const outRoot = path.resolve(import.meta.dirname, '../src/content/docs');
const repoUrl = 'https://github.com/jonathanagustin/uds-k3d-takserver';
// Root-relative, including the Pages base. The link checker rejects relative
// links, and it looks these paths up against the built routes.
const siteBase = '/uds-k3d-takserver';
// The demo videos are assets on the fixed `demo` release. GitHub serves a
// release download as application/octet-stream, and the user-attachments
// players in the README only work on github.com, so the build copies the
// videos into public/demo/ and Pages serves them as video/mp4. The posters
// in public/demo/ are committed. The copies are gitignored.
const demoRelease = `${repoUrl}/releases/download/demo`;
const demoDir = path.resolve(import.meta.dirname, '../public/demo');

const pages = [
  { src: 'README.md', slug: 'index', label: 'Getting started' },
  { src: 'CONTRIBUTING.md', slug: 'contributing', label: 'Contributing' },
  { src: 'docs/networking.md', slug: 'networking', label: 'Networking' },
  { src: 'docs/sso.md', slug: 'sso', label: 'Single sign-on' },
  { src: 'docs/configuration.md', slug: 'configuration', label: 'TAK Server' },
  { src: 'docs/cloudtak.md', slug: 'cloudtak', label: 'CloudTAK' },
  { src: 'docs/atak-device.md', slug: 'atak-device', label: 'ATAK test device' },
  { src: 'docs/building.md', slug: 'building', label: 'Building images' },
  { src: 'docs/data.md', slug: 'data', label: 'Data' },
  { src: 'docs/profiles.md', slug: 'profiles', label: 'Values profiles' },
  { src: 'docs/ci.md', slug: 'ci', label: 'CI workflows' },
  { src: 'docs/benchmarks.md', slug: 'benchmarks', label: 'Benchmarks' },
  { src: 'SECURITY.md', slug: 'security', label: 'Reporting a vulnerability' },
  { src: 'docs/justifications.md', slug: 'justifications', label: 'Policy exemptions' },
  { src: 'CHANGELOG.md', slug: 'changelog', label: 'Changelog' },
];

function posix(value) {
  return value.split(path.sep).join('/');
}

function normalizeRepoPath(value) {
  const parts = [];
  for (const part of value.split('/')) {
    if (part === '' || part === '.') continue;
    if (part === '..') parts.pop();
    else parts.push(part);
  }
  return parts.join('/');
}

function siteHref(toSlug, hash) {
  const pathname = toSlug === 'index' ? `${siteBase}/` : `${siteBase}/${toSlug}/`;
  return `${pathname}${hash}`;
}

function quote(value) {
  return JSON.stringify(value);
}

function firstHeading(markdown) {
  const match = markdown.match(/^#\s+(.+?)\s*$/m);
  return match ? match[1].trim() : '';
}

function firstParagraph(markdown) {
  const lines = markdown.split('\n');
  const paragraph = [];
  let seenHeading = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!seenHeading) {
      if (trimmed.startsWith('#')) seenHeading = true;
      continue;
    }
    if (paragraph.length === 0) {
      if (trimmed === '' || trimmed.startsWith('#') || trimmed.startsWith('|') || trimmed.startsWith('>') || trimmed.startsWith('-') || trimmed.startsWith('```') || trimmed.startsWith('<') || trimmed.startsWith('[!') || trimmed.startsWith('![') || trimmed.startsWith('[![')) {
        continue;
      }
      paragraph.push(trimmed);
      continue;
    }
    if (trimmed === '' || trimmed.startsWith('#')) break;
    paragraph.push(trimmed);
  }
  let text = paragraph.join(' ');
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
  text = text.replace(/[*_`]/g, '');
  if (text.length > 180) {
    text = `${text.slice(0, 177).replace(/\s+\S*$/, '')}...`;
  }
  return text;
}

function lastUpdated(src) {
  try {
    const iso = execFileSync('git', ['log', '-1', '--format=%cI', '--', src], {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    return iso ? iso.slice(0, 10) : '';
  } catch {
    return '';
  }
}

function frontmatter(page, markdown) {
  const title = firstHeading(markdown) || page.label;
  const description = firstParagraph(markdown) || page.label;
  const updated = lastUpdated(page.src);
  const lines = [
    '---',
    `title: ${quote(title)}`,
    `description: ${quote(description)}`,
    `editUrl: ${quote(`${repoUrl}/edit/main/${page.src}`)}`,
  ];
  if (updated) lines.push(`lastUpdated: ${updated}`);
  lines.push('sidebar:');
  lines.push(`  label: ${quote(page.label)}`);
  if (page.order !== undefined) lines.push(`  order: ${page.order}`);
  lines.push('---', '');
  return lines.join('\n');
}

function mapProse(markdown, rewrite) {
  return markdown
    .split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g)
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part
        .split(/(`[^`\n]*`)/g)
        .map((bit, bitIndex) => (bitIndex % 2 === 1 ? bit : rewrite(bit)))
        .join('');
    })
    .join('');
}

function stripDestination(destination) {
  const trimmed = destination.trim();
  const titled = trimmed.match(/^(\S+)\s+("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')$/);
  const target = titled ? titled[1] : trimmed;
  const suffix = titled ? ` ${titled[2]}` : '';
  const hashAt = target.indexOf('#');
  const pathPart = hashAt === -1 ? target : target.slice(0, hashAt);
  const hash = hashAt === -1 ? '' : target.slice(hashAt);
  return { pathPart, hash, suffix };
}

function rewriteDestination(fromSrc, destination, byPath) {
  const { pathPart, hash, suffix } = stripDestination(destination);
  if (pathPart === '' || pathPart.startsWith('#')) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(pathPart) || pathPart.startsWith('//')) return null;

  const fromDir = posix(path.posix.dirname(fromSrc));
  const base = fromDir === '.' ? '' : fromDir;
  const joined = pathPart.startsWith('/') ? pathPart.slice(1) : path.posix.join(base, pathPart);
  let resolved = normalizeRepoPath(joined);
  const directoryLink = pathPart.endsWith('/');
  if (resolved.endsWith('/')) resolved = resolved.slice(0, -1);
  // Docs show the demo stills and clip posters from docs-site/public/, so the
  // same file works on GitHub (a repository path) and on the site (served
  // from the site root).
  if (resolved.startsWith('docs-site/public/')) {
    return `${siteBase}/${resolved.slice('docs-site/public/'.length)}${hash}${suffix}`;
  }

  const candidates = [resolved];
  if (!resolved.endsWith('.md')) candidates.push(`${resolved}.md`, `${resolved}/index.md`);
  for (const candidate of candidates) {
    const target = byPath.get(candidate);
    if (target) return `${siteHref(target, hash)}${suffix}`;
  }
  if (resolved === 'adr') return `${siteHref('adr', hash)}${suffix}`;

  const absolute = path.join(repoRoot, resolved);
  let kind = 'blob';
  if (directoryLink) kind = 'tree';
  else if (existsSync(absolute) && statSync(absolute).isDirectory()) kind = 'tree';
  else if (!existsSync(absolute)) {
    console.warn(`sync-docs: ${fromSrc} links to missing path ${resolved}`);
  }
  return `${repoUrl}/${kind}/main/${resolved}${hash}${suffix}`;
}

async function fetchDemoVideos() {
  // demo-videos.intoto.jsonl lists each video's sha256. A copy that does not
  // match is downloaded again, and a download that does not match fails.
  const response = await fetch(`${demoRelease}/demo-videos.intoto.jsonl`);
  if (!response.ok) throw new Error(`demo-videos.intoto.jsonl: HTTP ${response.status}`);
  const envelope = JSON.parse((await response.text()).trim().split('\n')[0]);
  const statement = JSON.parse(Buffer.from(envelope.payload, 'base64').toString('utf8'));
  await mkdir(demoDir, { recursive: true });
  const names = [];
  for (const subject of statement.subject) {
    const want = subject.digest.sha256;
    const file = path.join(demoDir, subject.name);
    const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
    if (existsSync(file) && sha(await readFile(file)) === want) {
      names.push(subject.name);
      continue;
    }
    const video = await fetch(`${demoRelease}/${subject.name}`);
    if (!video.ok) throw new Error(`${subject.name}: HTTP ${video.status}`);
    const bytes = Buffer.from(await video.arrayBuffer());
    if (sha(bytes) !== want) throw new Error(`${subject.name}: sha256 does not match the provenance`);
    await writeFile(file, bytes);
    names.push(subject.name);
  }
  return new Set(names);
}

function embedDemoVideos(markdown, videos) {
  // A README line that is only a user-attachments URL is GitHub's inline
  // player. On the site it becomes a <video> for the next demo download link.
  // A line that is only a poster linking to a demo release video (a chapter
  // clip on a doc page, written as [![alt](poster)](video) so GitHub shows
  // the poster) becomes a <video> with that poster.
  const lines = markdown.split('\n');
  return lines
    .map((line, index) => {
      const clip = line
        .trim()
        .match(/^\[!\[([^\]]*)\]\(([^)\s]+\.(?:jpg|png|webp))\)\]\(https:\/\/github\.com\/[^)\s]+\/releases\/download\/demo\/([\w.-]+\.mp4)\)$/);
      if (clip) {
        if (!videos.has(clip[3])) return line;
        const label = clip[1].replace(/"/g, '&quot;');
        return [
          `<video controls preload="none" playsinline width="1280" height="720" poster="${clip[2]}" aria-label="${label}">`,
          `  <source src="${siteBase}/demo/${clip[3]}" type="video/mp4" />`,
          `</video>`,
        ].join('\n');
      }
      if (!/^https:\/\/github\.com\/user-attachments\/assets\/\S+$/.test(line.trim())) return line;
      const next = lines.slice(index + 1).join('\n').match(/releases\/download\/demo\/([\w.-]+\.mp4)/);
      if (!next || !videos.has(next[1])) return line;
      const base = next[1].replace(/\.mp4$/, '');
      return [
        `<video controls preload="none" playsinline width="1280" height="720" poster="${siteBase}/demo/${base}.jpg">`,
        `  <source src="${siteBase}/demo/${next[1]}" type="video/mp4" />`,
        `</video>`,
      ].join('\n');
    })
    .join('\n');
}

function dropFirstHeading(markdown) {
  // Starlight prints the frontmatter title as the page heading, so the body's
  // own first H1 would show twice.
  return markdown.replace(/^#\s+.+\r?\n(\r?\n)?/m, '');
}

function dropGithubOnly(markdown) {
  // Text between <!-- github-only:start --> and <!-- github-only:end --> is
  // for readers on github.com, such as the line that points at this site.
  return markdown.replace(/[ \t]*<!-- github-only:start -->[\s\S]*?<!-- github-only:end -->[ \t]*\r?\n?(\r?\n)?/g, '');
}

function titleLinkLabels(markdown, fromSrc, headings) {
  // A link whose text is the file path, like [docs/sso.md](docs/sso.md),
  // shows that page's title instead. On the site the path is not a file the
  // reader can open.
  return mapProse(markdown, (prose) =>
    prose.replace(/\[([A-Za-z0-9_./-]+\.md)\]\(([^)]+)\)/g, (full, label, destination) => {
      const { pathPart } = stripDestination(destination);
      const fromDir = posix(path.posix.dirname(fromSrc));
      const resolved = normalizeRepoPath(path.posix.join(fromDir === '.' ? '' : fromDir, pathPart));
      if (label !== pathPart && normalizeRepoPath(label) !== resolved) return full;
      const heading = headings.get(resolved);
      return heading ? `[${heading}](${destination})` : full;
    }),
  );
}

// GitHub's workflow badge.svg is reliable on github.com (camo can fetch it).
// On the docs site it has shown as a broken image in Chrome, so the site build
// swaps it for the shields.io workflow-status badge, which sets CORP to
// cross-origin. Keep both URLs in sync when either changes.
const githubTestBadge =
  'https://github.com/jonathanagustin/uds-k3d-takserver/actions/workflows/test.yaml/badge.svg?branch=main';
const siteTestBadge =
  'https://img.shields.io/github/actions/workflow/status/jonathanagustin/uds-k3d-takserver/test.yaml?branch=main&label=Test';

function rewriteLinks(markdown, fromSrc, byPath) {
  // Replace the destination of every ](url), including links whose label is an
  // image or inline code. Fenced code is left untouched.
  return mapProse(markdown, (prose) => {
    let next = prose
      .replace(/\]\(([^)]+)\)/g, (full, destination) => {
        const rewritten = rewriteDestination(fromSrc, destination, byPath);
        return rewritten === null ? full : `](${rewritten})`;
      })
      // The README uses raw HTML for its centered, width-limited screenshots.
      // Those src paths are repo-relative too, so rewrite them the same way.
      .replace(/(<img\s[^>]*\bsrc=")([^"]+)(")/g, (full, before, destination, after) => {
        const rewritten = rewriteDestination(fromSrc, destination, byPath);
        return rewritten === null ? full : `${before}${rewritten}${after}`;
      });
    if (fromSrc === 'README.md') {
      next = next.split(githubTestBadge).join(siteTestBadge);
    }
    return next;
  });
}

async function adrPages() {
  const names = (await readdir(path.join(repoRoot, 'adr')))
    .filter((name) => name.endsWith('.md') && name !== 'template.md')
    .sort();
  return names.map((name, index) => {
    const id = name.replace(/\.md$/, '');
    const order = Number(id.slice(0, id.indexOf('-'))) || index + 1;
    return {
      src: `adr/${name}`,
      slug: `adr/${id}`,
      label: id,
      order,
    };
  });
}

async function writePage(page, byPath, videos, headings) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  const body = raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
  const local = titleLinkLabels(dropGithubOnly(dropFirstHeading(body)), page.src, headings);
  let content = rewriteLinks(local, page.src, byPath);
  content = embedDemoVideos(content, videos);
  const markdown = `${frontmatter(page, body)}${content}`;
  const destination = path.join(outRoot, `${page.slug}.md`);
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, markdown.endsWith('\n') ? markdown : `${markdown}\n`);
}

function adrIndex(adrs) {
  const items = adrs
    .map((page) => `- [${page.heading}](${siteHref(page.slug, '')})`)
    .join('\n');
  return `---
title: "Architecture decisions"
description: "Why the package is put together the way it is."
editUrl: ${quote(`${repoUrl}/tree/main/adr`)}
sidebar:
  label: "Index"
  order: 0
---

The records below are the files in \`adr/\`. [\`adr/template.md\`](${repoUrl}/blob/main/adr/template.md) is the shape of a new one, not a decision.

${items}
`;
}

const adrs = await adrPages();
for (const page of adrs) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  page.heading = firstHeading(raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')) || page.label;
  page.label = page.heading;
}
const all = [...pages, ...adrs];
const byPath = new Map(all.map((page) => [page.src, page.slug]));
const headings = new Map();
for (const page of all) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  headings.set(page.src, firstHeading(raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')) || page.label);
}

await rm(outRoot, { recursive: true, force: true });
await mkdir(outRoot, { recursive: true });
let videos = new Set();
try {
  videos = await fetchDemoVideos();
} catch (error) {
  // CI must publish the players. A local build without network keeps the
  // download links and warns.
  if (process.env.CI) throw error;
  console.warn(`sync-docs: demo videos not copied: ${error.message}`);
}
for (const page of all) await writePage(page, byPath, videos, headings);
await writeFile(path.join(outRoot, 'adr/index.md'), adrIndex(adrs));
// Starlight's own /404 route reads this entry with getEntry(). draft keeps
// it out of the [...slug] pages in a production build, so the two routes do
// not both try to write /404.
await writeFile(
  path.join(outRoot, '404.md'),
  `---
title: "Page not found"
draft: true
description: "That page is not in these guides."
editUrl: false
sidebar:
  hidden: true
---

That page is not in these guides. The [overview](${siteHref('index', '')}) lists what is published.
`,
);
console.log(`sync-docs: wrote ${all.length + 2} pages`);
