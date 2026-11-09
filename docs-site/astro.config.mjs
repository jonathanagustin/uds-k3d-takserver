// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightGitHubAlerts from 'starlight-github-alerts';
import starlightLinksValidator from 'starlight-links-validator';
import starlightLlmsTxt from 'starlight-llms-txt';
import starlightSidebarTopics from 'starlight-sidebar-topics';
import { readFileSync } from 'node:fs';

const versions = JSON.parse(readFileSync(new URL('./src/generated/versions.json', import.meta.url), 'utf8'));

// Follow UDS's learning/concepts/tasks/reference order, scoped to one package.
// Version topics and page slugs remain independent of this navigation grouping.
const sidebarTemplate = [
  {
    label: 'Getting started',
    items: [
      { label: 'Home', slug: 'index' },
      { label: 'Install and deploy', slug: 'getting-started' },
    ],
  },
  {
    label: 'Concepts',
    items: [
      { label: 'Networking', slug: 'networking' },
      { label: 'Single sign-on', slug: 'sso' },
      { label: 'Policy exemptions', slug: 'justifications' },
    ],
  },
  {
    label: 'How-to guides',
    items: [{ autogenerate: { directory: 'how-to' } }],
  },
  {
    label: 'Reference',
    items: [
      { label: 'TAK Server', slug: 'configuration' },
      { label: 'CloudTAK', slug: 'cloudtak' },
      { label: 'ATAK test device', slug: 'atak-device' },
      { label: 'Data', slug: 'data' },
      { label: 'Values profiles', slug: 'profiles' },
    ],
  },
  {
    label: 'Project',
    items: [
      { label: 'Building images', slug: 'building' },
      { label: 'CI workflows', slug: 'ci' },
      { label: 'Review rules for main', slug: 'branch-protection' },
      { label: 'Benchmarks', slug: 'benchmarks' },
      { label: 'Contributing', slug: 'contributing' },
      { label: 'Reporting a vulnerability', slug: 'security' },
      { label: 'Changelog', slug: 'changelog' },
      { label: 'Architecture decisions', items: [{ autogenerate: { directory: 'adr' } }] },
    ],
  },
];
function versionItems(version) {
  const route = (slug) => version.prefix ? (slug === 'index' ? version.prefix : `${version.prefix}/${slug}`) : slug;
  const versionEntries = (entries) => entries.flatMap((item) => {
    if (item.slug) return version.pages.includes(item.slug) ? [{ ...item, slug: route(item.slug) }] : [];
    if (item.items) {
      const items = versionEntries(item.items);
      return items.length ? [{ ...item, collapsed: true, items }] : [];
    }
    const directory = item.autogenerate.directory;
    return version.pages.some((page) => page.startsWith(`${directory}/`))
      ? [{ autogenerate: { directory: route(directory) } }] : [];
  });
  return versionEntries(sidebarTemplate);
}
const topics = versions.map((version) => ({
  id: version.id, label: version.label,
  link: `/uds-takserver/${version.prefix ? version.prefix + '/' : ''}`,
  items: versionItems(version),
}));

// Project site: https://jonathanagustin.github.io/uds-takserver/
// `site` is the origin. `base` is the repository path GitHub Pages serves.
export default defineConfig({
  site: 'https://jonathanagustin.github.io',
  base: '/uds-takserver',
  trailingSlash: 'always',
  integrations: [
    // Renders the ```mermaid blocks in the README and the guides. It has to
    // come before Starlight so it sees the fences first.
    mermaid({ theme: 'default', autoTheme: true }),
    starlight({
      title: 'TAK Server on UDS',
      description:
        'TAK Server packaged for UDS, with Keycloak sign-in, CloudTAK, and default-deny networking.',
      // Use the canonical wordmark in the header; retain the beacon favicon.
      logo: {
        light: '../assets/tak-on-uds-light.svg',
        dark: '../assets/tak-on-uds-dark.svg',
        replacesTitle: true,
      },
      head: [
        {
          tag: 'meta',
          attrs: {
            property: 'og:image',
            content: 'https://jonathanagustin.github.io/uds-takserver/og.png',
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
            content: 'https://jonathanagustin.github.io/uds-takserver/og.png',
          },
        },
      ],
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/jonathanagustin/uds-takserver',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/jonathanagustin/uds-takserver/edit/main/',
      },
      lastUpdated: true,
      customCss: ['./src/styles/custom.css'],
      components: {
        Hero: './src/components/Hero.astro',
        DraftContentNotice: './src/components/DraftContentNotice.astro',
        ThemeSelect: './src/components/ThemeSelect.astro',
        MarkdownContent: './src/components/MarkdownContent.astro',
        Search: './src/components/Search.astro',
      },
      // Shiki has no LogQL grammar. Show those blocks as plain text without a
      // build warning.
      expressiveCode: { shiki: { langAlias: { logql: 'txt' } } },
      // Renders GitHub alert syntax (> [!NOTE], > [!WARNING]) as callouts, so
      // the same markdown works on GitHub and on the site.
      plugins: [
        starlightSidebarTopics(topics, { exclude: ['/404'] }),
        starlightGitHubAlerts(),
        starlightLinksValidator(),
        starlightLlmsTxt({
          promote: ['index*', 'getting-started*'],
        }),
      ],

    }),
  ],
});
