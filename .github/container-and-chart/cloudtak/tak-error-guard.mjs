// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// node-tak resolves TAK.connect() before the TLS handshake finishes.
// CloudTAK then awaits certificate setup and only after that listens for
// 'error'. A reset in that gap is emitted with no listener, and Node exits.
//
// holdErrorsUntilListener keeps those errors until a real 'error' listener
// is registered by on, addListener, once, prependListener, or
// prependOnceListener. That registration removes the holder before it
// returns, then emits each buffered error once. Later emits use Node's own
// listener list: a once listener is gone after one event, and an emit with
// no listener is uncaught. If no listener arrives, the deadline emits the
// buffered errors with no holder. This module does not retry and does not
// replace EventEmitter.

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
    let timer;
    const originalOn = tak.on;
    const originalOnce = tak.once;
    const originalPrepend = tak.prependListener;
    const originalPrependOnce = tak.prependOnceListener;

    function userListeners() {
        return tak.listeners('error').filter((fn) => fn !== onError);
    }

    function restoreMethods() {
        delete tak.on;
        delete tak.addListener;
        delete tak.once;
        delete tak.prependListener;
        delete tak.prependOnceListener;
    }

    function detach() {
        clearTimeout(timer);
        tak.removeListener('error', onError);
        restoreMethods();
    }

    function failClosed() {
        if (settled) return;
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) tak.emit('error', err);
    }

    // Called only after the real listener is already stored. The holder is
    // gone before this returns, so a later emit in the same turn cannot be
    // swallowed by a leftover listener.
    function release() {
        if (settled || userListeners().length === 0) return;
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) tak.emit('error', err);
    }

    function onError(err) {
        if (!settled) buffered.push(err);
    }

    function wrap(original) {
        return function(event, listener) {
            const result = original.call(this, event, listener);
            if (!settled && event === 'error' && listener !== onError) release();
            return result;
        };
    }

    originalOn.call(tak, 'error', onError);
    tak.on = tak.addListener = wrap(originalOn);
    tak.once = wrap(originalOnce);
    tak.prependListener = wrap(originalPrepend);
    tak.prependOnceListener = wrap(originalPrependOnce);
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
