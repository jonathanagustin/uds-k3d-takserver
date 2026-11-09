// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

export const repositoryUrl = 'https://github.com/jonathanagustin/uds-takserver';
// Historical GitHub source URLs redirect after the rename; published OCI refs do not.
export const legacyGithubRepositoryUrl = 'https://github.com/jonathanagustin/uds-k3d-takserver';
const badgePath = '/actions/workflows/test.yaml/badge.svg?branch=main';
export const siteTestBadge =
  'https://img.shields.io/github/actions/workflow/status/jonathanagustin/uds-takserver/test.yaml?branch=main&label=Test';

export function rewriteTestBadge(prose) {
  return prose.split(repositoryUrl + badgePath).join(siteTestBadge)
    .split(legacyGithubRepositoryUrl + badgePath).join(siteTestBadge);
}

export function rewriteLegacyGithubLinks(home) {
  return home.replaceAll(legacyGithubRepositoryUrl, (match, offset, source) => {
    const next = source[offset + match.length];
    // Require a URL boundary, so a different repository with this prefix stays intact.
    return next === undefined || /[\/#?\s"'`<>)]/.test(next) ? repositoryUrl : match;
  });
}
