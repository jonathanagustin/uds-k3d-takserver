// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';

// Project site: https://jonathanagustin.github.io/uds-k3d-takserver/
// `site` is the origin. `base` is the repository path GitHub Pages serves.
export default defineConfig({
  site: 'https://jonathanagustin.github.io',
  base: '/uds-k3d-takserver',
  trailingSlash: 'always',
  integrations: [
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
      plugins: [starlightLinksValidator()],
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
