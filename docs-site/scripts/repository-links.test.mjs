// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  repositoryUrl, legacyGithubRepositoryUrl, siteTestBadge,
  rewriteTestBadge, rewriteLegacyGithubLinks,
} from '../src/lib/repository-links.mjs';

test('both actual GitHub Test badge URLs use the site-safe badge', () => {
  for (const repo of [repositoryUrl, legacyGithubRepositoryUrl]) {
    assert.equal(rewriteTestBadge(`![Test](${repo}/actions/workflows/test.yaml/badge.svg?branch=main)`),
      `![Test](${siteTestBadge})`);
  }
  assert.equal(rewriteTestBadge(siteTestBadge), siteTestBadge);
  const unrelated = 'https://github.com/another/project/actions/workflows/test.yaml/badge.svg?branch=main';
  assert.equal(rewriteTestBadge(unrelated), unrelated);
});

test('legacy home source links migrate while current and unrelated links stay intact', () => {
  for (const suffix of ['', '/', '/issues/32', '#readme', '?tab=readme-ov-file']) {
    assert.equal(rewriteLegacyGithubLinks(`[Source](${legacyGithubRepositoryUrl}${suffix})`),
      `[Source](${repositoryUrl}${suffix})`);
  }
  for (const value of [repositoryUrl, repositoryUrl + '/issues/32',
    legacyGithubRepositoryUrl + '-other', 'https://example.com/source']) {
    assert.equal(rewriteLegacyGithubLinks(value), value);
  }
});

test('historical package coordinates are not GitHub source-link redirects', () => {
  const legacyName = legacyGithubRepositoryUrl.split('/').at(-1);
  const coordinate = `oci://ghcr.io/jonathanagustin/${legacyName}/takserver:0.10.0-upstream`;
  const mixed = `${legacyGithubRepositoryUrl}/tree/v0.10.0 ${coordinate}`;
  assert.equal(rewriteLegacyGithubLinks(mixed), `${repositoryUrl}/tree/v0.10.0 ${coordinate}`);
  assert.equal(rewriteTestBadge(coordinate), coordinate);
});
