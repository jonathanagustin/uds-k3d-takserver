// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { docsReleaseTags } from './published-releases.mjs';

export function selectReleaseTags(tags, limit = 5) {
  const releases = tags.map((tag) => {
    const match = /^v(\d+)\.(\d+)\.(\d+)$/.exec(tag);
    return match ? { tag, parts: match.slice(1).map(Number) } : null;
  }).filter((release) => release && (release.parts[0] > 0 || release.parts[1] >= 7));
  releases.sort((a, b) => b.parts[0] - a.parts[0] || b.parts[1] - a.parts[1] || b.parts[2] - a.parts[2]);
  const minors = new Set();
  return releases.filter(({ parts }) => {
    const minor = parts.slice(0, 2).join('.');
    if (minors.has(minor)) return false;
    minors.add(minor);
    return true;
  }).slice(0, limit).map(({ tag, parts }) => ({
    id: `v${parts[0]}-${parts[1]}`, ref: tag, minor: parts.slice(0, 2).join('.'),
  }));
}

async function pageSlugs(directory, prefix = '') {
  const pages = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const name = `${prefix}${entry.name}`;
    if (entry.isDirectory()) pages.push(...await pageSlugs(path.join(directory, entry.name), `${name}/`));
    else if (/\.mdx?$/.test(name) && name !== '404.md') pages.push(name.replace(/\.mdx?$/, ''));
  }
  return pages.sort();
}

export async function buildVersions(repoRoot = path.resolve(import.meta.dirname, '../..')) {
  const siteRoot = path.resolve(import.meta.dirname, '..');
  const output = path.join(siteRoot, 'src/content/docs');
  const git = (...args) => execFileSync('git', args, { cwd: repoRoot, encoding: 'utf8' }).trim();
  const gitTags = git('tag', '--list').split('\n').filter(Boolean);
  const { tags: candidates, mode } = await docsReleaseTags(gitTags);
  console.log(`build-versions: ${mode === 'git-preview' ? 'local Git tag preview (publication not verified)' : 'published release inventory'}`);
  const tags = candidates.filter((tag) => selectReleaseTags([tag]).length).filter((tag) => {
    try { git('cat-file', '-e', `${tag}:docs-site/`); return true; } catch { return false; }
  });
  const releases = selectReleaseTags(tags);
  if (!releases.length) throw new Error('No stable v0.7+ release with docs-site/ was found. Fetch tags before building.');
  const versions = releases.map((release, index) => ({ ...release,
    prefix: index === 0 ? '' : release.id,
    label: index === 0 ? `Latest (${release.minor})` : release.minor,
  }));
  versions.push({ id: 'main', prefix: 'main', ref: 'main', label: 'main (unreleased)' });
  const temporary = await mkdtemp(path.join(tmpdir(), 'tak-docs-versions-'));
  const worktrees = [];
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  try {
    // Download shared video assets once from the current checkout. Released
    // source worktrees are read-only inputs and use the same static assets.
    const main = versions.at(-1);
    const order = [main, ...versions.slice(0, -1)];
    for (const version of order) {
      let source = repoRoot;
      if (version.id !== 'main') {
        source = path.join(temporary, version.id);
        git('worktree', 'add', '--detach', source, version.ref);
        worktrees.push(source);
      }
      const destination = path.join(output, version.prefix);
      execFileSync(process.execPath, [path.join(siteRoot, 'scripts/sync-docs.mjs'),
        '--repo-root', source, '--output-root', destination,
        '--url-prefix', version.prefix, '--source-ref', version.ref,
        '--git-ref', version.id === 'main' ? 'HEAD' : version.ref,
        '--version-id', version.id, '--keep-output',
        ...(version.id === 'main' ? [] : ['--skip-video-download']),
        // Only the latest landing is a current project shell. Guides and
        // archived homes still use their checked-out release source.
        ...(version.prefix === '' ? ['--include-404', '--landing-source',
          path.join(repoRoot, 'docs-site/src/home.mdx')] : []),
      ], { cwd: siteRoot, stdio: 'inherit' });
      // Root also contains the version subdirectories, which belong to their
      // own manifests. Keep only this version's routes.
      version.pages = (await pageSlugs(destination)).filter((slug) =>
        version.prefix !== '' || !versions.some((other) => other.prefix && slug.startsWith(`${other.prefix}/`)));
      version.commit = git('rev-parse', version.id === 'main' ? 'HEAD' : version.ref);
    }
    await mkdir(path.join(siteRoot, 'src/generated'), { recursive: true });
    await writeFile(path.join(siteRoot, 'src/generated/versions.json'), `${JSON.stringify(versions, null, 2)}\n`);
    console.log(`build-versions: ${versions.map((version) => `${version.label}=${version.ref}`).join(', ')}`);
    return versions;
  } finally {
    for (const worktree of worktrees.reverse()) git('worktree', 'remove', worktree);
    await rm(temporary, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildVersions();
