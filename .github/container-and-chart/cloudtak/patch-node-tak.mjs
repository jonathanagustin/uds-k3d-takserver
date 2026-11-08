// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// node-tak 12.31.0 and 12.31.1 destroy the TLS socket in the 'end' handler.
// Node emits 'end' before 'error' when the handshake is reset, so destroy()
// removes the error listener and the following 'error' is uncaught.
// 'close' still destroys the socket after 'error' has been delivered.

import fs from 'node:fs';

const NEEDLE = `                // After emitting 'end', a reconnect triggered synchronously
                // by a listener may have already replaced this.client with
                // a fresh socket and reset this.destroyed to false.
                // Re-check socket identity so we don't destroy the
                // newly-created socket.
                if (client === this.client && !this.destroyed) {
                    this.destroy();
                }`;

const REPLACEMENT = `                // Do not destroy the socket here. Node emits 'end' before
                // 'error' when a TLS handshake is reset, and destroy()
                // would remove the error listener. The 'close' handler
                // still destroys the socket.`;

export function patchNodeTakSource(source) {
    const count = source.split(NEEDLE).length - 1;
    if (count !== 1) {
        throw new Error(`node-tak end-handler destroy() found ${count} times, expected 1`);
    }
    return source.replace(NEEDLE, REPLACEMENT);
}

const entry = process.argv[1] ?? '';
if (entry.endsWith('patch-node-tak.mjs')) {
    const file = process.argv[2];
    if (!file) {
        console.error('usage: node patch-node-tak.mjs DIST_INDEX_JS');
        process.exit(2);
    }
    fs.writeFileSync(file, patchNodeTakSource(fs.readFileSync(file, 'utf8')));
}
