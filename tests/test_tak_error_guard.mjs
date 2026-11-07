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

import { patchNodeTakSource } from '../.github/container-and-chart/cloudtak/patch-node-tak.mjs';
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

test('a second emit after once is uncaught, with no leftover holder', () => {
    for (const method of ['once', 'prependOnceListener']) {
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        const seen = [];
        tak[method]('error', (got) => seen.push(got.message));
        assert.equal(tak.listenerCount('error'), 1, method);
        tak.emit('error', reset('error1'));
        assert.deepEqual(seen, ['error1'], method);
        assert.equal(tak.listenerCount('error'), 0, method);
        assert.throws(() => tak.emit('error', reset('error2')), /error2/);
    }
});

test('an emit after every listener is removed is uncaught', () => {
    const tak = new EventEmitter();
    holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
    const seen = [];
    const first = (got) => seen.push(got.message);
    const second = (got) => seen.push('other ' + got.message);
    tak.on('error', first);
    tak.on('error', second);
    tak.removeListener('error', first);
    tak.removeListener('error', second);
    assert.equal(tak.listenerCount('error'), 0);
    assert.throws(() => tak.emit('error', reset('after-remove')), /after-remove/);
    assert.deepEqual(seen, []);
});

test('once exhaustion and removal are uncaught in a fresh process', () => {
    const onceResult = spawnSync(process.execPath, ['--input-type=module', '-e', `
        import { EventEmitter } from 'node:events';
        import { holdErrorsUntilListener } from ${JSON.stringify(path.join(cloudtakDir, 'tak-error-guard.mjs'))};
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        tak.once('error', (err) => console.log('GOT ' + err.message));
        tak.emit('error', Object.assign(new Error('error1'), { code: 'ECONNRESET' }));
        tak.emit('error', Object.assign(new Error('error2'), { code: 'ECONNRESET' }));
        console.log('STILL_UP');
    `], { encoding: 'utf8' });
    assert.match(onceResult.stdout, /GOT error1/);
    assert.match(onceResult.stderr, /error2/);
    assert.notEqual(onceResult.status, 0);
    assert.doesNotMatch(onceResult.stdout, /STILL_UP/);

    const removed = spawnSync(process.execPath, ['--input-type=module', '-e', `
        import { EventEmitter } from 'node:events';
        import { holdErrorsUntilListener } from ${JSON.stringify(path.join(cloudtakDir, 'tak-error-guard.mjs'))};
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        const fn = () => console.log('GOT');
        tak.on('error', fn);
        tak.removeListener('error', fn);
        tak.emit('error', Object.assign(new Error('after-remove'), { code: 'ECONNRESET' }));
        console.log('STILL_UP');
    `], { encoding: 'utf8' });
    assert.match(removed.stderr, /after-remove/);
    assert.notEqual(removed.status, 0);
    assert.doesNotMatch(removed.stdout, /STILL_UP|GOT/);
});

test('same-turn register and emit delivers once for every registration method', async () => {
    for (const method of ['on', 'addListener', 'once', 'prependListener', 'prependOnceListener']) {
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        const seen = [];
        tak[method]('error', (got) => seen.push(got.message));
        tak.emit('error', reset(method));
        await flush();
        assert.deepEqual(seen, [method], method);
    }
});

test('several buffered errors are replayed once, in order', async () => {
    const tak = new EventEmitter();
    holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
    tak.emit('error', reset('one'));
    tak.emit('error', reset('two'));
    const seen = [];
    tak.on('error', (got) => seen.push(got.message));
    await flush();
    assert.deepEqual(seen, ['one', 'two']);
    tak.emit('error', reset('three'));
    assert.deepEqual(seen, ['one', 'two', 'three']);
});

test('once consumes one buffered error and the next is not held', () => {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', `
        import { EventEmitter } from 'node:events';
        import { holdErrorsUntilListener } from ${JSON.stringify(path.join(cloudtakDir, 'tak-error-guard.mjs'))};
        const tak = new EventEmitter();
        holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
        tak.emit('error', Object.assign(new Error('first'), { code: 'ECONNRESET' }));
        tak.emit('error', Object.assign(new Error('second'), { code: 'ECONNRESET' }));
        tak.once('error', (err) => console.log('GOT ' + err.message));
        setTimeout(() => console.log('STILL_UP'), 50);
    `], { encoding: 'utf8' });
    assert.match(result.stdout, /GOT first/);
    assert.match(result.stderr, /second/);
    assert.notEqual(result.status, 0);
    assert.doesNotMatch(result.stdout, /STILL_UP/);
});

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

test('a buffered error is delivered on registration, and the next emit after removal is uncaught', () => {
    const tak = new EventEmitter();
    holdErrorsUntilListener(tak, { deadlineMs: 5_000 });
    tak.emit('error', reset('buffered'));
    const seen = [];
    const fn = (got) => seen.push(got.message);
    tak.addListener('error', fn);
    assert.deepEqual(seen, ['buffered']);
    tak.removeListener('error', fn);
    assert.throws(() => tak.emit('error', reset('after-remove')), /after-remove/);
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

test('patcher rejects a node-tak build without the end-handler destroy', () => {
    assert.throws(() => patchNodeTakSource('nothing here'), /found 0 times/);
});

function realTakReset(version) {
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'tak-real-'));
    const api = path.join(work, 'api');
    fs.mkdirSync(api);
    fs.copyFileSync(path.join(cloudtakDir, 'tak-error-guard.mjs'), path.join(api, 'tak-error-guard.mjs'));
    fs.copyFileSync(path.join(cloudtakDir, 'uds-tak-error-guard.mjs'), path.join(api, 'uds-tak-error-guard.mjs'));
    const installed = spawnSync('npm', ['install', '--silent', '--prefix', api, `@tak-ps/node-tak@${version}`], {
        encoding: 'utf8',
    });
    assert.equal(installed.status, 0, installed.stderr);
    return { work, api };
}

test('pinned node-tak 12.31.0 and locked 12.31.1 replay one reset across the pool gap', () => {
    // package.json of CloudTAK v13.112.3 says ^12.31.0. Its lockfile installs
    // 12.31.1. ConnectionPool.#add is not imported: it needs Postgres and the
    // rest of the API. The await below is that function's gap.
    for (const version of ['12.31.0', '12.31.1']) {
    const { work, api } = realTakReset(version);
    const installedVersion = JSON.parse(fs.readFileSync(path.join(api, 'node_modules', '@tak-ps', 'node-tak', 'package.json'), 'utf8')).version;
    assert.equal(installedVersion, version);
    const dist = path.join(api, 'node_modules', '@tak-ps', 'node-tak', 'dist', 'index.js');
    const original = fs.readFileSync(dist, 'utf8');
    fs.writeFileSync(dist, patchNodeTakSource(original));
    const key = path.join(work, 'key.pem');
    const cert = path.join(work, 'cert.pem');
    const made = spawnSync('openssl', [
        'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=localhost',
    ], { encoding: 'utf8' });
    assert.equal(made.status, 0, made.stderr);
    fs.writeFileSync(path.join(api, 'pool.mjs'), `
        import fs from 'node:fs';
        import net from 'node:net';
        import TAK from '@tak-ps/node-tak';
        if (process.env.EXPECT_GUARD === '1' && !TAK.connect.__takErrorGuard) {
            console.error('GUARD_NOT_INSTALLED');
            process.exit(2);
        }
        const server = net.createServer((socket) => socket.destroy());
        await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
        const url = new URL('ssl://127.0.0.1:' + server.address().port);
        const tak = await TAK.connect(url, {
            cert: fs.readFileSync(process.env.CERT, 'utf8'),
            key: fs.readFileSync(process.env.KEY, 'utf8'),
        }, { id: 'pool' });
        // CloudTAK v13.112.3 ConnectionPool.#add awaits certificate setup
        // between TAK.connect() and tak.on('error').
        await new Promise((resolve) => setTimeout(resolve, 100));
        const seen = [];
        tak.on('error', (err) => seen.push(err.message));
        await new Promise((resolve) => setTimeout(resolve, 50));
        server.close();
        if (seen.length !== 1 || !seen[0].includes('before secure TLS connection was established')) {
            console.error('SEEN ' + JSON.stringify(seen));
            process.exit(4);
        }
        console.log('REAL_TAK_ONE_RESET');
    `);
    const withGuard = spawnSync(process.execPath, [path.join(api, 'pool.mjs')], {
        cwd: api,
        encoding: 'utf8',
        env: {
            ...process.env,
            EXPECT_GUARD: '1',
            NODE_OPTIONS: `--max-old-space-size=640 --import ${path.join(api, 'uds-tak-error-guard.mjs')}`,
            CERT: cert,
            KEY: key,
        },
    });
    const bare = spawnSync(process.execPath, [path.join(api, 'pool.mjs')], {
        cwd: api,
        encoding: 'utf8',
        env: { ...process.env, EXPECT_GUARD: '', NODE_OPTIONS: '', CERT: cert, KEY: key },
    });
    fs.writeFileSync(dist, original);
    const unpatched = spawnSync(process.execPath, [path.join(api, 'pool.mjs')], {
        cwd: api,
        encoding: 'utf8',
        env: { ...process.env, EXPECT_GUARD: '', NODE_OPTIONS: '', CERT: cert, KEY: key },
    });
    fs.rmSync(work, { recursive: true, force: true });
    assert.equal(withGuard.status, 0, `${version}\n${withGuard.stdout}\n${withGuard.stderr}`);
    assert.match(withGuard.stdout, /REAL_TAK_ONE_RESET/);
    assert.notEqual(bare.status, 0, version);
    assert.match(bare.stderr, /before secure TLS connection was established/);
    assert.notEqual(unpatched.status, 0, version);
    assert.match(unpatched.stderr, /before secure TLS connection was established/);
    }
});

function cloudTakRetryMs(retryCount) {
    // ConnectionPool.retry in CloudTAK v13.112.3. The first retry does not
    // wait. Later waits grow by one second and stop at 15 seconds.
    const isFirstRetry = retryCount === 0;
    const nextRetry = Math.min(retryCount + 1, 15);
    return isFirstRetry ? 0 : Math.min(nextRetry * 1000, 15_000);
}

test('clean EOF reconnects through patched node-tak and the pool retry delays', () => {
    assert.equal(cloudTakRetryMs(0), 0);
    assert.equal(cloudTakRetryMs(1), 2_000);
    assert.equal(cloudTakRetryMs(14), 15_000);
    assert.equal(cloudTakRetryMs(20), 15_000);
    for (const version of ['12.31.0', '12.31.1']) {
        const { work, api } = realTakReset(version);
        const dist = path.join(api, 'node_modules', '@tak-ps', 'node-tak', 'dist', 'index.js');
        fs.writeFileSync(dist, patchNodeTakSource(fs.readFileSync(dist, 'utf8')));
        const key = path.join(work, 'key.pem');
        const cert = path.join(work, 'cert.pem');
        const made = spawnSync('openssl', [
            'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=localhost',
        ], { encoding: 'utf8' });
        assert.equal(made.status, 0, made.stderr);
        fs.writeFileSync(path.join(api, 'eof.mjs'), `
            import fs from 'node:fs';
            import tls from 'node:tls';
            import TAK from '@tak-ps/node-tak';
            const cert = fs.readFileSync(process.env.CERT, 'utf8');
            const key = fs.readFileSync(process.env.KEY, 'utf8');
            let connections = 0;
            let firstSocket;
            let markConnected;
            const connected = new Promise((resolve) => { markConnected = resolve; });
            const server = tls.createServer({ cert, key }, (socket) => {
                connections += 1;
                console.log('SERVER ' + connections);
                if (connections === 1) {
                    firstSocket = socket;
                    markConnected();
                }
            });
            await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
            const tak = await TAK.connect(new URL('ssl://127.0.0.1:' + server.address().port), {
                cert, key,
            }, { id: 'pool' });
            await connected;
            // Same yield as ConnectionPool.#add before it registers listeners.
            await new Promise((resolve) => setTimeout(resolve, 20));
            let retry = 0;
            let retrying = false;
            async function retryLikePool(kind) {
                console.log('EVENT ' + kind);
                if (retrying) return;
                retrying = true;
                const isFirstRetry = retry === 0;
                const nextRetry = Math.min(retry + 1, 15);
                const retryms = isFirstRetry ? 0 : Math.min(nextRetry * 1000, 15000);
                retry = nextRetry;
                console.log('DELAY ' + retryms);
                if (retryms > 0) await new Promise((resolve) => setTimeout(resolve, retryms));
                await tak.reconnect();
                console.log('RECONNECTED');
                retrying = false;
            }
            tak.on('close', () => retryLikePool('close'))
                .on('end', () => retryLikePool('end'))
                .on('error', (err) => retryLikePool('error ' + err.message));
            firstSocket.end();
            const deadline = Date.now() + 2000;
            while (Date.now() < deadline && connections < 2) {
                await new Promise((resolve) => setTimeout(resolve, 20));
            }
            tak.destroy();
            server.close();
            if (connections < 2) {
                console.error('NO_RECONNECT ' + connections);
                process.exit(4);
            }
            console.log('CLEAN_EOF_RECONNECT');
        `);
        const result = spawnSync(process.execPath, [path.join(api, 'eof.mjs')], {
            cwd: api,
            encoding: 'utf8',
            timeout: 15_000,
            env: {
                ...process.env,
                NODE_OPTIONS: `--max-old-space-size=640 --import ${path.join(api, 'uds-tak-error-guard.mjs')}`,
                CERT: cert,
                KEY: key,
            },
        });
        fs.rmSync(work, { recursive: true, force: true });
        assert.equal(result.status, 0, `${version}\n${result.stdout}\n${result.stderr}`);
        assert.match(result.stdout, /CLEAN_EOF_RECONNECT/);
        assert.match(result.stdout, /DELAY 0/);
        assert.match(result.stdout, /SERVER 2/);
        assert.doesNotMatch(result.stderr, /uncaught|NO_RECONNECT/);
    }
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
