// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

const repository = 'jonathanagustin/uds-takserver';
const api = `https://api.github.com/repos/${repository}`;
const stable = /^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/;

export function releaseInventoryMode(environment = process.env) {
  const preview = environment.DOCS_LOCAL_TAG_PREVIEW;
  if (preview !== undefined && preview !== '' && preview !== '1') throw new Error('Invalid local docs preview mode');
  if (environment.CI && preview === '1') throw new Error('CI requires published release inventory');
  return preview === '1' ? 'git-preview' : 'published';
}

function validate(record) {
  if (!record || Array.isArray(record) || !Number.isSafeInteger(record.id) || record.id < 1
      || typeof record.tag_name !== 'string' || !record.tag_name || record.tag_name.length > 128
      || /[\x00-\x20\x7f]/.test(record.tag_name)
      || typeof record.draft !== 'boolean' || typeof record.prerelease !== 'boolean'
      || record.url !== `${api}/releases/${record.id}`) throw new Error('Invalid published release inventory');
  return record;
}

async function get(endpoint, fetcher, token) {
  const response = await fetcher(`${api}${endpoint}`, {
    headers: { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
      ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    redirect: 'error', signal: AbortSignal.timeout(20_000),
  });
  if (response.status !== 200 || !response.body) throw new Error('Published release API unavailable');
  const reader = response.body.getReader();
  let bytes = 0;
  const chunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 2 * 1024 * 1024) throw new Error('Published release API response exceeds limit');
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally {
    await reader.cancel();
  }
}

export async function publishedReleaseTags({ fetcher = fetch, token = '', requestedTag = '' } = {}) {
  if (requestedTag && !stable.test(requestedTag)) throw new Error('Expected a published stable release tag');
  const releases = new Map();
  const ids = new Set();
  let complete = false;
  for (let page = 1; page <= 10; page++) {
    const rows = await get(`/releases?per_page=100&page=${page}`, fetcher, token);
    if (!Array.isArray(rows) || rows.length > 100) throw new Error('Invalid published release inventory page');
    for (const value of rows) {
      const release = validate(value);
      if (ids.has(release.id) || releases.has(release.tag_name)) throw new Error('Ambiguous published release inventory');
      ids.add(release.id);
      releases.set(release.tag_name, release);
    }
    if (rows.length < 100) { complete = true; break; }
  }
  if (!complete) throw new Error('Published release inventory exceeds page limit');
  const tags = [...releases.values()].filter((release) =>
    !release.draft && !release.prerelease && stable.test(release.tag_name)).map((release) => release.tag_name);
  if (!tags.length) throw new Error('No published stable releases found');
  if (requestedTag) {
    // This endpoint intentionally returns 404 for an unpublished draft.
    const release = validate(await get(`/releases/tags/${requestedTag}`, fetcher, token));
    if (release.tag_name !== requestedTag || release.draft || release.prerelease
        || !tags.includes(requestedTag) || releases.get(requestedTag).id !== release.id)
      throw new Error('Requested docs release is not published');
  }
  return tags;
}

export async function docsReleaseTags(gitTags, { environment = process.env, fetcher = fetch } = {}) {
  const mode = releaseInventoryMode(environment);
  if (mode === 'git-preview') {
    if (environment.DOCS_RELEASE_TAG) throw new Error('Release publication checks cannot use local preview mode');
    return { tags: gitTags, mode };
  }
  const published = await publishedReleaseTags({ fetcher, token: environment.GH_TOKEN || '',
    requestedTag: environment.DOCS_RELEASE_TAG || '' });
  // An incomplete Git checkout must not silently advertise an older release.
  if (published.some((tag) => !gitTags.includes(tag))) throw new Error('Published release tag missing from checkout; fetch tags');
  return { tags: published, mode };
}
