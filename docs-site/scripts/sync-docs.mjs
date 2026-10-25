// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Copies the repository markdown into src/content/docs with the frontmatter
// Starlight requires, and points links at the published page or at GitHub.
// The copies are gitignored. The files in the repository stay the source.

import { execFileSync } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '../..');
const outRoot = path.resolve(import.meta.dirname, '../src/content/docs');
const repoUrl = 'https://github.com/jonathanagustin/uds-k3d-takserver';
// Root-relative, including the Pages base. The link checker rejects relative
// links, and it looks these paths up against the built routes.
const siteBase = '/uds-k3d-takserver';

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
      if (trimmed === '' || trimmed.startsWith('#') || trimmed.startsWith('|') || trimmed.startsWith('>') || trimmed.startsWith('-') || trimmed.startsWith('```') || trimmed.startsWith('<')) {
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

function rewriteLinks(markdown, fromSrc, byPath) {
  // Replace the destination of every ](url), including links whose label is an
  // image or inline code. Fenced code is left untouched.
  return mapProse(markdown, (prose) =>
    prose.replace(/\]\(([^)]+)\)/g, (full, destination) => {
      const rewritten = rewriteDestination(fromSrc, destination, byPath);
      return rewritten === null ? full : `](${rewritten})`;
    }),
  );
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

async function writePage(page, byPath) {
  const raw = await readFile(path.join(repoRoot, page.src), 'utf8');
  const body = raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
  const markdown = `${frontmatter(page, body)}${rewriteLinks(body, page.src, byPath)}`;
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

await rm(outRoot, { recursive: true, force: true });
await mkdir(outRoot, { recursive: true });
for (const page of all) await writePage(page, byPath);
await writeFile(path.join(outRoot, 'adr/index.md'), adrIndex(adrs));
await writeFile(
  path.join(outRoot, '404.md'),
  `---
title: "Page not found"
description: "That page is not in these guides."
editUrl: false
sidebar:
  hidden: true
---

That page is not in these guides. The [overview](${siteHref('index', '')}) lists what is published.
`,
);
console.log(`sync-docs: wrote ${all.length + 2} pages`);
