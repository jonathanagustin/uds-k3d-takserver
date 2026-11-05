// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightGitHubAlerts from 'starlight-github-alerts';
import starlightLinksValidator from 'starlight-links-validator';

// Project site: https://jonathanagustin.github.io/uds-k3d-takserver/
// `site` is the origin. `base` is the repository path GitHub Pages serves.
export default defineConfig({
  site: 'https://jonathanagustin.github.io',
  base: '/uds-k3d-takserver',
  trailingSlash: 'always',
  integrations: [
    // Renders the ```mermaid blocks in the README and the guides. It has to
    // come before Starlight so it sees the fences first.
    mermaid({ theme: 'default', autoTheme: true }),
    starlight({
      title: 'uds-k3d-takserver',
      description:
        'TAK Server packaged for UDS, with Keycloak sign-in, CloudTAK, and default-deny networking.',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/jonathanagustin/uds-k3d-takserver',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/jonathanagustin/uds-k3d-takserver/edit/main/',
      },
      lastUpdated: true,
      customCss: ['./src/styles/custom.css'],
      // Shiki has no LogQL grammar. Show those blocks as plain text without a
      // build warning.
      expressiveCode: { shiki: { langAlias: { logql: 'txt' } } },
      // Renders GitHub alert syntax (> [!NOTE], > [!WARNING]) as callouts, so
      // the same markdown works on GitHub and on the site.
      plugins: [starlightGitHubAlerts(), starlightLinksValidator()],
      sidebar: [
        {
          label: 'Overview',
          items: [
            { label: 'Getting started', slug: 'index' },
            { label: 'Contributing', slug: 'contributing' },
          ],
        },
        {
          label: 'Architecture',
          items: [
            { label: 'Networking', slug: 'networking' },
            { label: 'Single sign-on', slug: 'sso' },
          ],
        },
        {
          label: 'Packages',
          items: [
            { label: 'TAK Server', slug: 'configuration' },
            { label: 'CloudTAK', slug: 'cloudtak' },
            { label: 'ATAK test device', slug: 'atak-device' },
          ],
        },
        {
          label: 'Operations',
          items: [
            { label: 'Building images', slug: 'building' },
            { label: 'Data', slug: 'data' },
            { label: 'Values profiles', slug: 'profiles' },
            { label: 'CI workflows', slug: 'ci' },
            { label: 'Benchmarks', slug: 'benchmarks' },
          ],
        },
        {
          label: 'Security',
          items: [
            { label: 'Reporting a vulnerability', slug: 'security' },
            { label: 'Policy exemptions', slug: 'justifications' },
          ],
        },
        {
          label: 'Decisions',
          items: [{ autogenerate: { directory: 'adr' } }],
        },
        {
          label: 'Reference',
          items: [{ label: 'Changelog', slug: 'changelog' }],
        },
      ],
    }),
  ],
});
