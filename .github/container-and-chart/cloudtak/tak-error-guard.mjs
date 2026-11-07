// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// node-tak resolves TAK.connect() before the TLS handshake finishes.
// CloudTAK then awaits certificate setup and only after that listens for
// 'error'. A reset in that gap is emitted with no listener, and Node exits.
//
// holdErrorsUntilListener keeps those errors until a real 'error' listener
// is registered by on, addListener, once, prependListener, or
// prependOnceListener. It then removes itself and emits each error once,
// so the pool's own retry runs. If that listener never arrives, the same
// errors are emitted with no holder, which is Node's usual uncaught
// exception. This module does not retry and does not replace EventEmitter.

import { EventEmitter } from 'node:events';

// Certificate setup is one await, but that await can do network I/O.
// Past this, a missing listener is a fault and must surface.
export const LISTENER_DEADLINE_MS = 20_000;

export function holdErrorsUntilListener(tak, { deadlineMs = LISTENER_DEADLINE_MS } = {}) {
    if (!(tak instanceof EventEmitter)) {
        throw new TypeError('holdErrorsUntilListener requires an EventEmitter');
    }
    const buffered = [];
    let settled = false;
    // Set in newListener, before the real listener is stored and before
    // on/addListener/once/prependListener/prependOnceListener return.
    // A same-turn emit then reaches only that listener.
    let passThrough = false;
    let timer;

    function userListeners() {
        return tak.listeners('error').filter((fn) => fn !== onError);
    }

    function detach() {
        clearTimeout(timer);
        tak.removeListener('error', onError);
        tak.removeListener('newListener', onNew);
    }

    function failClosed() {
        if (settled) return;
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) tak.emit('error', err);
    }

    function release() {
        if (settled) return;
        if (userListeners().length === 0) {
            if (buffered.length > 0) failClosed();
            return;
        }
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) {
            if (tak.listeners('error').length === 0) {
                tak.emit('error', err);
                return;
            }
            tak.emit('error', err);
        }
    }

    function onError(err) {
        if (settled || passThrough) return;
        buffered.push(err);
    }

    function onNew(event, listener) {
        if (settled || event !== 'error' || listener === onError) return;
        passThrough = true;
        queueMicrotask(release);
    }

    tak.on('newListener', onNew);
    tak.on('error', onError);
    timer = setTimeout(failClosed, deadlineMs);
    if (typeof timer.unref === 'function') timer.unref();
    return tak;
}

export function install(TAK) {
    if (!TAK || typeof TAK.connect !== 'function' || TAK.connect.__takErrorGuard) return TAK;
    const orig = TAK.connect;
    function connect(...args) {
        return Promise.resolve(orig.apply(this, args)).then((tak) => {
            holdErrorsUntilListener(tak);
            return tak;
        });
    }
    connect.__takErrorGuard = true;
    TAK.connect = connect;
    return TAK;
}
