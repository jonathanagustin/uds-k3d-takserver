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
    let timer;

    function userListeners() {
        return tak.listeners('error').filter((fn) => fn !== onError);
    }

    function detach() {
        clearTimeout(timer);
        tak.removeListener('error', onError);
        tak.removeListener('newListener', onNew);
        tak.removeListener('removeListener', onRemove);
    }

    function release() {
        if (settled || userListeners().length === 0) return;
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) tak.emit('error', err);
    }

    function failClosed() {
        if (settled) return;
        if (userListeners().length > 0) {
            release();
            return;
        }
        settled = true;
        const pending = buffered.splice(0);
        detach();
        for (const err of pending) tak.emit('error', err);
    }

    function onError(err) {
        if (!settled) buffered.push(err);
    }

    // newListener is emitted by every registration method, before the
    // listener is stored. The microtask runs after that store.
    function onNew(event) {
        if (event === 'error') queueMicrotask(release);
    }

    function onRemove(event) {
        if (event !== 'error' || settled) return;
        queueMicrotask(() => {
            if (!settled && userListeners().length === 0 && buffered.length > 0) {
                // The pool added a listener and removed it before delivery.
                // The deadline still ends the hold.
            }
        });
    }

    tak.on('newListener', onNew);
    tak.on('removeListener', onRemove);
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
