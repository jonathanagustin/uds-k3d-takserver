// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { holdErrorsUntilListener } from '../.github/container-and-chart/cloudtak/tak-error-guard.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const cloudtakDir = path.resolve(here, '../.github/container-and-chart/cloudtak');

function reset(message = 'Client network socket disconnected before secure TLS connection was established') {
    const err = new Error(message);
    err.code = 'ECONNRESET';
    return err;
}

function flush() {
    return new Promise((resolve) => {
        setImmediate(resolve);
    });
}

test('addListener, once, and prependOnce each receive a buffered reset once', async () => {
    for (const method of ['addListener', 'once', 'prependListener', 'prependOnceListener']) {
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        const err = reset(method);
        tak.emit('error', err);
        const seen = [];
        tak[method]('error', (got) => seen.push(got));
        await flush();
        assert.deepEqual(seen.map((item) => item.message), [method], method);
        if (method === 'once' || method === 'prependOnceListener') {
            assert.throws(() => tak.emit('error', reset('again')), /again/);
        }
    }
});

test('removing the pool listener before delivery does not keep the error forever', async () => {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', `
        import { EventEmitter } from 'node:events';
        import { holdErrorsUntilListener } from ${JSON.stringify(path.join(cloudtakDir, 'tak-error-guard.mjs'))};
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 40 });
        const err = new Error('removed before delivery');
        err.code = 'ECONNRESET';
        tak.emit('error', err);
        const fn = () => {};
        tak.addListener('error', fn);
        tak.removeListener('error', fn);
        setTimeout(() => console.log('STILL_UP'), 200);
    `], { encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /removed before delivery/);
    assert.doesNotMatch(result.stdout, /STILL_UP/);
});

test('a missing pool listener fails closed after the deadline', () => {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', `
        import { EventEmitter } from 'node:events';
        import { holdErrorsUntilListener } from ${JSON.stringify(path.join(cloudtakDir, 'tak-error-guard.mjs'))};
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 40 });
        const err = new Error('no pool listener');
        err.code = 'ECONNRESET';
        tak.emit('error', err);
        setTimeout(() => console.log('STILL_UP'), 200);
    `], { encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /no pool listener/);
    assert.doesNotMatch(result.stdout, /STILL_UP/);
});

test('production NODE_OPTIONS preload installs and one TLS reset reaches addListener', () => {
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'tak-guard-'));
    const api = path.join(work, 'api');
    const pkg = path.join(api, 'node_modules', '@tak-ps', 'node-tak');
    fs.mkdirSync(pkg, { recursive: true });
    fs.copyFileSync(path.join(cloudtakDir, 'tak-error-guard.mjs'), path.join(api, 'tak-error-guard.mjs'));
    fs.copyFileSync(path.join(cloudtakDir, 'uds-tak-error-guard.mjs'), path.join(api, 'uds-tak-error-guard.mjs'));
    fs.writeFileSync(path.join(pkg, 'package.json'), JSON.stringify({
        name: '@tak-ps/node-tak',
        type: 'module',
        exports: './index.js',
    }));
    fs.writeFileSync(path.join(pkg, 'index.js'), `
        import { EventEmitter } from 'node:events';
        import tls from 'node:tls';
        export default class TAK extends EventEmitter {
            static connect(port) {
                const tak = new TAK();
                const client = tls.connect({ host: '127.0.0.1', port, rejectUnauthorized: false });
                client.on('error', (err) => tak.emit('error', err));
                return tak;
            }
        }
    `);
    fs.writeFileSync(path.join(api, 'dist-index.mjs'), `
        import net from 'node:net';
        import TAK from '@tak-ps/node-tak';
        if (!TAK.connect.__takErrorGuard) {
            console.error('GUARD_NOT_INSTALLED');
            process.exit(2);
        }
        if (process.execArgv.some((arg) => String(arg).includes('tak-error-guard') || String(arg).includes('--import'))) {
            console.error('IMPORT_IN_EXECARGV ' + JSON.stringify(process.execArgv));
            process.exit(3);
        }
        const server = net.createServer((socket) => socket.destroy());
        await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
        const tak = await TAK.connect(server.address().port);
        await new Promise((resolve) => setTimeout(resolve, 100));
        const seen = [];
        tak.addListener('error', (err) => seen.push(err.code || err.message));
        await new Promise((resolve) => setTimeout(resolve, 100));
        server.close();
        if (seen.length !== 1) {
            console.error('SEEN ' + JSON.stringify(seen));
            process.exit(4);
        }
        console.log('POOL_GOT_ONE_RESET');
    `);
    const start = fs.readFileSync(path.join(cloudtakDir, 'start.sh'), 'utf8');
    assert.match(start, /NODE_OPTIONS="\$\{NODE_OPTIONS:\+\$\{NODE_OPTIONS\} \}--import \/home\/etl\/api\/uds-tak-error-guard\.mjs"/);
    const preload = path.join(api, 'uds-tak-error-guard.mjs');
    const nodeOptions = `--max-old-space-size=640 --import ${preload}`;
    const result = spawnSync(process.execPath, [path.join(api, 'dist-index.mjs')], {
        cwd: api,
        encoding: 'utf8',
        env: { ...process.env, NODE_OPTIONS: nodeOptions },
    });
    fs.rmSync(work, { recursive: true, force: true });
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    assert.match(result.stdout, /POOL_GOT_ONE_RESET/);
    assert.doesNotMatch(result.stderr, /GUARD_NOT_INSTALLED|IMPORT_IN_EXECARGV/);
});
