// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// CloudTAK's connection pool calls TAK.connect(), then awaits certificate
// setup, and only then listens for 'error'. node-tak resolves connect()
// before the TLS handshake finishes. If messaging resets the handshake in
// that gap, the socket error is re-emitted on the TAK object with no
// listener, and Node exits. Kubernetes counts that as a container restart.
//
// This holds those errors until the pool adds its own 'error' listener,
// then gives them to that listener. The pool's existing retry, whose delay
// is capped, is what reconnects. This file does not retry and does not
// keep any other exception.

export function holdErrorsUntilListener(tak) {
    const buffered = [];
    let held = true;

    function onError(err) {
        if (held) buffered.push(err);
    }

    tak.on('error', onError);
    const origOn = tak.on;
    tak.on = function on(event, listener) {
        const ret = origOn.call(this, event, listener);
        if (held && event === 'error' && listener !== onError) {
            held = false;
            tak.removeListener('error', onError);
            for (const err of buffered.splice(0)) {
                tak.emit('error', err);
            }
        }
        return ret;
    };
    return tak;
}

export function install(TAK) {
    if (!TAK || typeof TAK.connect !== 'function' || TAK.connect.__takErrorGuard) return TAK;
    const orig = TAK.connect;
    const wrapped = async function connect(...args) {
        const tak = await orig.apply(this, args);
        holdErrorsUntilListener(tak);
        return tak;
    };
    wrapped.__takErrorGuard = true;
    TAK.connect = wrapped;
    return TAK;
}

const imported = process.execArgv.some((arg) => arg.includes('tak-error-guard'));
if (imported) {
    const { default: TAK } = await import('@tak-ps/node-tak');
    install(TAK);
}
