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
import { parseArgs } from 'node:util';
import { howToSteps } from './how-to-ui.mjs';

const { values: args } = parseArgs({ options: {
  'repo-root': { type: 'string' },
  'landing-source': { type: 'string' },
  'output-root': { type: 'string' },
  'url-prefix': { type: 'string', default: '' },
  'git-ref': { type: 'string', default: 'HEAD' },
  'source-ref': { type: 'string', default: 'main' },
  'version-id': { type: 'string', default: 'main' },
  'keep-output': { type: 'boolean', default: false },
  'skip-video-download': { type: 'boolean', default: false },
  'include-404': { type: 'boolean', default: false },
} });
const repoRoot = path.resolve(args['repo-root'] || path.resolve(import.meta.dirname, '../..'));
const outRoot = path.resolve(args['output-root'] || path.resolve(import.meta.dirname, '../src/content/docs'));
const sourceRef = args['source-ref'];
const gitRef = args['git-ref'];
const unreleased = args['version-id'] === 'main';
const repoUrl = 'https://github.com/jonathanagustin/uds-takserver';
// Root-relative, including the Pages base. The link checker rejects relative
// links, and it looks these paths up against the built routes.
const assetBase = '/uds-takserver';
const siteBase = `${assetBase}${args['url-prefix'] ? '/' + args['url-prefix'] : ''}`;
// The demo videos are assets on the fixed `demo` release. GitHub serves a
// release download as application/octet-stream, and the user-attachments
// players in the README only work on github.com, so the build copies the
// videos into public/demo/ and Pages serves them as video/mp4. The posters
// in public/demo/ are committed. The copies are gitignored.
// Preserve the published demo source and its historical provenance.
const demoRelease = 'https://github.com/jonathanagustin/uds-k3d-takserver/releases/download/demo';
const demoDir = path.resolve(import.meta.dirname, '../public/demo');

const pages = [
  { src: 'README.md', slug: 'getting-started', label: 'Getting started' },
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
  { src: 'docs/branch-protection.md', slug: 'branch-protection', label: 'Review rules for main' },
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

// Keep original line offsets so removing a prose heading cannot alter code.
function* markdownLines(markdown) {
  let fence = null;
  let start = 0;
  for (const raw of markdown.split(/(?<=\n)/)) {
    const line = raw.replace(/\r?\n$/, '');
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    const fenced = Boolean(fence || marker);
    if (fence) {
      if (marker && marker[1][0] === fence.character && marker[1].length >= fence.length && marker[2].trim() === '') fence = null;
    } else if (marker) {
      fence = { character: marker[1][0], length: marker[1].length };
    }
    yield { line, start, end: start + raw.length, fenced };
    start += raw.length;
  }
}

function firstHeading(markdown) {
  for (const { line, fenced } of markdownLines(markdown)) {
    const match = !fenced && /^#\s+(.+?)\s*$/.exec(line);
    if (match) return match[1].trim();
  }
  return '';
}

function firstParagraph(markdown) {
  const paragraph = [];
  for (const { line, fenced } of markdownLines(dropGithubOnly(markdown))) {
    if (fenced) {
      if (paragraph.length) break;
      continue;
    }
    const trimmed = line.trim();
    // README's centered description is an HTML paragraph. Image-only badge
    // and branding paragraphs have no text and cannot become the description.
    const htmlParagraph = /^<p(?:\s[^>]*)?>(.*?)<\/p>\s*$/i.exec(trimmed);
    if (htmlParagraph) {
      const text = htmlParagraph[1].replace(/<!--.*?-->/g, '').replace(/<[^>]*>/g, '').trim();
      if (!text) continue;
      if (!paragraph.length) paragraph.push(text);
      break;
    }
    if (paragraph.length === 0) {
      if (trimmed === '' || trimmed.startsWith('#') || trimmed.startsWith('|') || trimmed.startsWith('>') || trimmed.startsWith('-') || trimmed.startsWith('<') || trimmed.startsWith('[!') || trimmed.startsWith('![')) continue;
      paragraph.push(trimmed);
      continue;
    }
    if (trimmed === '' || trimmed.startsWith('#') || trimmed.startsWith('<')) break;
    paragraph.push(trimmed);
  }
  let text = paragraph.join(' ');
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
  text = text.replace(/<[^>]*>/g, '').replace(/[*_`]/g, '');
  if (text.length > 180) {
    text = `${text.slice(0, 177).replace(/\s+\S*$/, '')}...`;
  }
  return text;
}

function lastUpdated(src) {
  try {
    const iso = execFileSync('git', ['log', '-1', '--format=%cI', gitRef, '--', src], {
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
    `editUrl: ${quote(`${repoUrl}/${unreleased ? 'edit' : 'blob'}/${sourceRef}/${page.src}`)}`,
  ];
  if (updated) lines.push(`lastUpdated: ${updated}`);
  if (unreleased) lines.push('banner:', `  content: ${quote('You are reading unreleased main documentation. Use the version selector for a released package.')}`);
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
    return `${assetBase}/${resolved.slice('docs-site/public/'.length)}${hash}${suffix}`;
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
  return `${repoUrl}/${kind}/${sourceRef}/${resolved}${hash}${suffix}`;
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
          `  <source src="${assetBase}/demo/${clip[3]}" type="video/mp4" />`,
          `</video>`,
        ].join('\n');
      }
      if (!/^https:\/\/github\.com\/user-attachments\/assets\/\S+$/.test(line.trim())) return line;
      const next = lines.slice(index + 1).join('\n').match(/releases\/download\/demo\/([\w.-]+\.mp4)/);
      if (!next || !videos.has(next[1])) return line;
      const base = next[1].replace(/\.mp4$/, '');
      return [
        `<video controls preload="none" playsinline width="1280" height="720" poster="${assetBase}/demo/${base}.jpg">`,
        `  <source src="${assetBase}/demo/${next[1]}" type="video/mp4" />`,
        `</video>`,
      ].join('\n');
    })
    .join('\n');
}

function dropFirstHeading(markdown) {
  // Starlight prints the frontmatter title as the page heading, so the body's
  // own first H1 would show twice. A shell comment inside a fence is not H1.
  for (const { line, start, end, fenced } of markdownLines(markdown)) {
    if (fenced || !/^#\s+.+/.test(line)) continue;
    return markdown.slice(0, start) + markdown.slice(end).replace(/^\r?\n/, '');
  }
  return markdown;
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

// README status badges that GitHub camo cannot fetch reliably are committed under
// docs-site/public/badges/ and linked with relative paths. Relative README images
// skip camo; sync-docs already maps docs-site/public/ onto the Pages root.
// Refresh release.svg when the version changes; scorecard.svg when the score changes.

// GitHub's workflow badge.svg is reliable on github.com (camo can fetch it).
// On the docs site it has shown as a broken image in Chrome, so the site build
// swaps it for the shields.io workflow-status badge, which sets CORP to
// cross-origin. Keep both URLs in sync when either changes.
const githubTestBadge =
  'https://github.com/jonathanagustin/uds-takserver/actions/workflows/test.yaml/badge.svg?branch=main';
const siteTestBadge =
  'https://img.shields.io/github/actions/workflow/status/jonathanagustin/uds-takserver/test.yaml?branch=main&label=Test';

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
      next = next.split(githubTestBadge.replace('/uds-takserver/', '/uds-k3d-takserver/')).join(siteTestBadge);
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

async function howToPages() {
  if (!existsSync(path.join(repoRoot, 'docs/how-to'))) return [];
  const names = (await readdir(path.join(repoRoot, 'docs/how-to')))
    .filter((name) => name.endsWith('.md') && !name.startsWith('_'))
    .sort();
  return names.map((name, index) => ({
    src: `docs/how-to/${name}`,
    slug: `how-to/${name.replace(/\.md$/, '')}`,
    label: name.replace(/\.md$/, ''),
    order: index + 1,
  }));
}

async function writePage(page, byPath, videos, headings) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  const body = raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
  const local = titleLinkLabels(dropGithubOnly(dropFirstHeading(body)), page.src, headings);
  let content = rewriteLinks(local, page.src, byPath);
  content = embedDemoVideos(content, videos);
  const steps = unreleased && page.src.startsWith('docs/how-to/') ? howToSteps(content) : null;
  const markdown = `${frontmatter(page, body)}${steps ?? content}`;
  const destination = path.join(outRoot, `${page.slug}.${steps ? 'mdx' : 'md'}`);
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
editUrl: ${quote(`${repoUrl}/tree/${sourceRef}/adr`)}
sidebar:
  label: "Index"
  order: 0
---

The records below are the files in \`adr/\`. [\`adr/template.md\`](${repoUrl}/blob/${sourceRef}/adr/template.md) is the shape of a new one, not a decision.

${items}
`;
}

const adrs = await adrPages();
const howTos = await howToPages();
for (const page of [...adrs, ...howTos]) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  page.heading = firstHeading(raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')) || page.label;
  page.label = page.heading;
}
const all = [...pages.filter((page) => existsSync(path.join(repoRoot, page.src))), ...adrs, ...howTos];
const byPath = new Map(all.map((page) => [page.src, page.slug]));
const headings = new Map();
for (const page of all) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  headings.set(page.src, firstHeading(raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')) || page.label);
}

if (!args['keep-output']) await rm(outRoot, { recursive: true, force: true });
await mkdir(outRoot, { recursive: true });
let videos = new Set();
try {
  if (!args['skip-video-download']) videos = await fetchDemoVideos();
  else videos = new Set((await readdir(demoDir)).filter((name) => name.endsWith('.mp4')));
} catch (error) {
  // CI must publish the players. A local build without network keeps the
  // download links and warns.
  if (process.env.CI) throw error;
  console.warn(`sync-docs: demo videos not copied: ${error.message}`);
}
for (const page of all) await writePage(page, byPath, videos, headings);
await writeFile(path.join(outRoot, 'adr/index.md'), adrIndex(adrs));
// Starlight's /404 route reads this entry with getEntry(). draft keeps it out
// of the [...slug] pages, so the two routes do not both try to write /404.
// DraftContentNotice.astro skips the draft banner for this entry.
if (args['include-404']) await writeFile(
  path.join(outRoot, '404.md'),
  `---
title: "Page not found"
draft: true
description: "That page is not in these guides."
editUrl: false
pagefind: false
sidebar:
  hidden: true
---

That page is not in these guides. The [home page](${siteHref('index', '')}) links to them.
`,
);
// The splash page is site-only. README.md is Getting started. A hash on the
// home URL is forwarded to that page so older links keep their section.
// home.mdx imports LegacyHomeHash from the copied path, src/content/docs/.
// A tag predating the splash page gets a small navigation shell; every guide
// body still comes from that tag. main uses its authored splash content.
// The latest root may explicitly use the current project landing while all
// guides and version metadata continue to come from the release source.
const currentLanding = Boolean(args['landing-source']);
const homePath = currentLanding ? path.resolve(args['landing-source']) : path.join(repoRoot, 'docs-site/src/home.mdx');
if (currentLanding && !existsSync(homePath)) throw new Error(`Landing source not found: ${homePath}`);
const componentPath = posix(path.relative(outRoot, path.resolve(import.meta.dirname, '../src/components/LegacyHomeHash.astro')));
const legacyImport = componentPath.startsWith('.') ? componentPath : `./${componentPath}`;
let home;
if (existsSync(homePath)) {
  home = await readFile(homePath, 'utf8');
  home = home.replace(/(^|[\s"'(=])\/uds-(?:k3d-)?takserver\//g, `$1${siteBase}/`);
  home = home.replaceAll('https://github.com/jonathanagustin/uds-k3d-takserver/', `${repoUrl}/`);
  home = home.replace('../../components/LegacyHomeHash.astro', legacyImport);
  if (currentLanding) {
    const front = /^---\r?\n([\s\S]*?)\r?\n---/.exec(home);
    if (!front) throw new Error('The current landing source requires frontmatter.');
    const fields = front[1].replace(/^editUrl:.*(?:\r?\n|$)/m, '');
    home = `---\n${fields}\neditUrl: ${quote(`${repoUrl}/edit/main/docs-site/src/home.mdx`)}\n---${home.slice(front[0].length)}`;
  } else if (!unreleased) home = home.replace(`${repoUrl}/edit/main/`, `${repoUrl}/blob/${sourceRef}/`);
} else {
  home = `---
title: TAK Server on UDS
description: Documentation for ${sourceRef}.
template: splash
hero:
  title: TAK Server on UDS
  tagline: Documentation for released package ${sourceRef}.
  actions:
    - text: Getting started
      link: ${siteHref('getting-started', '')}
      icon: right-arrow
editUrl: false
prev: false
next: false
sidebar:
  label: Home
---

import LegacyHomeHash from '${legacyImport}';
import { CardGrid, LinkCard } from '@astrojs/starlight/components';

<LegacyHomeHash />

[Getting started](${siteHref('getting-started', '')}) contains the deployment instructions for ${sourceRef}.

## Explore the documentation

<CardGrid>
  <LinkCard title="Deploy" href="${siteHref('getting-started', '')}" description="Installation and deployment instructions for ${sourceRef}." />
  <LinkCard title="Configure" href="${siteHref('configuration', '')}" description="Package variables, hosts, and configuration for this release." />
  <LinkCard title="Networking" href="${siteHref('networking', '')}" description="Understand ingress, service access, and network policy." />
  <LinkCard title="Back up" href="${siteHref('data', '')}" description="Database and volume backup procedures for this release." />
</CardGrid>
`;
}
if (unreleased) home = home.replace('---\n', `---\nbanner:\n  content: ${quote('You are reading unreleased main documentation. Use the version selector for a released package.')}\n`);
await writeFile(path.join(outRoot, 'index.mdx'), home.endsWith('\n') ? home : `${home}\n`);
console.log(`sync-docs: wrote ${all.length + 2} pages from ${sourceRef} to ${siteBase}/`);
