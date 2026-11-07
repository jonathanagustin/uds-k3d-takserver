// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';

import { holdErrorsUntilListener } from '../.github/container-and-chart/cloudtak/tak-error-guard.mjs';

function reset() {
    const err = new Error('Client network socket disconnected before secure TLS connection was established');
    err.code = 'ECONNRESET';
    return err;
}

test('a handshake reset before the pool listener is replayed once and does not throw', () => {
    const tak = new EventEmitter();
    holdErrorsUntilListener(tak);
    const err = reset();
    assert.doesNotThrow(() => tak.emit('error', err));
    const seen = [];
    tak.on('cot', () => {});
    tak.on('error', (got) => seen.push(got));
    assert.deepEqual(seen, [err]);
    const later = new Error('later');
    tak.emit('error', later);
    assert.deepEqual(seen, [err, later]);
});

test('an error after the pool is listening is delivered once', () => {
    const tak = new EventEmitter();
    holdErrorsUntilListener(tak);
    const seen = [];
    tak.on('error', (got) => seen.push(got));
    const err = reset();
    tak.emit('error', err);
    assert.deepEqual(seen, [err]);
});

test('buffering one connection does not hide an error on another', () => {
    const first = new EventEmitter();
    const second = new EventEmitter();
    holdErrorsUntilListener(first);
    assert.throws(() => second.emit('error', reset()), /secure TLS connection/);
});
