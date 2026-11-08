// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

export const base = '/uds-takserver';

export function versionForPath(pathname, versions) {
  const relative = pathname.replace(new RegExp(`^${base}/?`), '').replace(/\/$/, '');
  return versions.find((version) => version.prefix &&
    (relative === version.prefix || relative.startsWith(`${version.prefix}/`))) || versions[0];
}

export function relativePage(pathname, version) {
  const prefix = `${base}${version.prefix ? `/${version.prefix}` : ''}`;
  return pathname.slice(prefix.length).replace(/^\/|\/$/g, '') || 'index';
}

export function versionHref(version, page = 'index') {
  const available = version.pages.includes(page) ? page : 'index';
  return `${base}${version.prefix ? `/${version.prefix}` : ''}/${available === 'index' ? '' : available + '/'}`;
}
