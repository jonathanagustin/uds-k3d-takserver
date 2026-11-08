// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { setTimeout as delay } from 'node:timers/promises';

const transientCodes = new Set(['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EAI_AGAIN',
  'ENOTFOUND', 'ENETUNREACH', 'EHOSTUNREACH', 'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT', 'UND_ERR_SOCKET']);
function transientNetwork(error) {
  return error?.name === 'TimeoutError' || transientCodes.has(error?.code)
    || (error?.cause && transientNetwork(error.cause))
    || error?.errors?.some(transientNetwork);
}

// Three attempts, each with a 60-second deadline covering headers and body.
// Parsing, signature checks, and digest checks stay outside the retry boundary.
export async function download(url, { fetchImpl = fetch, sleep = delay } = {}) {
  for (let attempt = 0; attempt < 3; attempt++) {
    let retry = false;
    let failure;
    try {
      const response = await fetchImpl(url, { signal: AbortSignal.timeout(60_000) });
      if (!response.ok) {
        retry = response.status === 429 || (response.status >= 500 && response.status <= 599);
        failure = new Error(`${url}: HTTP ${response.status}`);
        await response.body?.cancel().catch(() => {});
      } else {
        return Buffer.from(await response.arrayBuffer());
      }
    } catch (error) {
      failure = error;
      retry = transientNetwork(error);
    }
    if (!retry || attempt === 2) throw failure;
    await sleep(1000 * (attempt + 1));
  }
}
