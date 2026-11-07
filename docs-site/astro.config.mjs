// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightGitHubAlerts from 'starlight-github-alerts';
import starlightLinksValidator from 'starlight-links-validator';
import starlightLlmsTxt from 'starlight-llms-txt';

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
      title: 'TAK Server on UDS',
      description:
        'TAK Server packaged for UDS, with Keycloak sign-in, CloudTAK, and default-deny networking.',
      // public/favicon.svg is the same mark, already served at /favicon.svg.
      // This path is the repository icon, so the header does not keep a second copy.
      logo: {
        src: '../assets/icon.svg',
      },
      head: [
        {
          tag: 'meta',
          attrs: {
            property: 'og:image',
            content: 'https://jonathanagustin.github.io/uds-k3d-takserver/og.png',
          },
        },
        {
          tag: 'meta',
          attrs: { property: 'og:image:width', content: '1200' },
        },
        {
          tag: 'meta',
          attrs: { property: 'og:image:height', content: '630' },
        },
        {
          tag: 'meta',
          attrs: {
            property: 'og:image:alt',
            content: 'TAK Server on UDS',
          },
        },
        {
          tag: 'meta',
          attrs: { name: 'twitter:card', content: 'summary_large_image' },
        },
        {
          tag: 'meta',
          attrs: {
            name: 'twitter:image',
            content: 'https://jonathanagustin.github.io/uds-k3d-takserver/og.png',
          },
        },
      ],
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
      components: {
        DraftContentNotice: './src/components/DraftContentNotice.astro',
      },
      // Shiki has no LogQL grammar. Show those blocks as plain text without a
      // build warning.
      expressiveCode: { shiki: { langAlias: { logql: 'txt' } } },
      // Renders GitHub alert syntax (> [!NOTE], > [!WARNING]) as callouts, so
      // the same markdown works on GitHub and on the site.
      plugins: [
        starlightGitHubAlerts(),
        starlightLinksValidator(),
        starlightLlmsTxt({
          promote: ['index*', 'getting-started*'],
        }),
      ],
      sidebar: [
        {
          label: 'Overview',
          items: [
            { label: 'Home', slug: 'index' },
            { label: 'Getting started', slug: 'getting-started' },
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
            { label: 'Review rules for main', slug: 'branch-protection' },
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
