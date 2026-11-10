#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Best-effort producer only. Missing proof omits a receipt, never acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


foundation = module('receipt_foundation', 'install-receipt.py')
artifacts = module('artifact_inputs', 'install-artifact-inputs.py')
checkpoint = artifacts.checkpoint
require = foundation.require
REPOSITORY = 'jonathanagustin/uds-takserver'
OMISSION_STAGES = frozenset({'operation', 'context', 'source-checkout', 'source-snapshot',
                             'pinned-key', 'cli-version', 'pinned-snapshot', 'execution',
                             'checkpoint-validation', 'checkpoint-archive', 'app-archive',
                             'bundle-selection', 'local-package-oci', 'bundle-oci',
                             'app-archive-stability', 'receipt-write'})
_omission_stage = 'operation'


def stage(value):
    global _omission_stage
    require(value in OMISSION_STAGES, 'unsupported stage')
    _omission_stage = value


def read_json(path, limit):
    require(path.stat().st_size <= limit, 'oversized evidence')
    return json.loads(path.read_bytes())


def context(env):
    stage('context')
    require(env.get('GITHUB_REPOSITORY') == REPOSITORY, 'unsupported repository')
    event = env.get('GITHUB_EVENT_NAME')
    require(event in ('push', 'pull_request', 'workflow_dispatch'), 'unsupported event')
    payload = read_json(Path(env['GITHUB_EVENT_PATH']), 2 * 1024 * 1024)
    if event == 'pull_request':
        require(payload.get('pull_request', {}).get('head', {}).get('repo', {}).get('full_name') ==
                REPOSITORY, 'fork evidence omitted')
    if event == 'workflow_dispatch':
        inputs = payload.get('inputs', {})
        require(inputs.get('trust_bundle', False) in (False, 'false') and
                inputs.get('diagnostic_case', 'none') == 'none', 'manual mode omitted')
    require(env.get('TEST_TYPE') == 'install' and env.get('TEST_FLAVOR') == 'upstream' and
            env.get('RECEIPT_DIAGNOSTIC') == 'none', 'unsupported scenario')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    require(arch is not None and env.get('AIRGAP_TEST') in ('true', 'false'), 'unsupported runner')
    airgap = env['AIRGAP_TEST'] == 'true'
    require(not airgap or arch == 'amd64', 'unsupported airgap runner')
    run_id, attempt = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_RUN_ATTEMPT', '')
    require(all(re.fullmatch(r'[1-9][0-9]*', item) for item in (run_id, attempt)), 'invalid run')
    return {'event': event, 'run_id': int(run_id), 'attempt': int(attempt), 'arch': arch,
            'scenario': 'install-airgap' if airgap else 'install'}


def snapshot(root, env):
    ctx = context(env)
    stage('source-checkout')
    return {'context': ctx, 'checkout': foundation.checkout_identity(root)}


def capture(root, env, directory):
    value = snapshot(root, env)
    stage('source-snapshot')
    with (directory / 'install-source.json').open('x') as output:
        json.dump(value, output, sort_keys=True)
        output.write('\n')
    # This option only records acquisition metadata. It cannot skip work.
    with Path(env['GITHUB_ENV']).open('a') as output:
        output.write('INSTALL_RECEIPT_METADATA=true\nINSTALL_RECEIPT_CHECKPOINT_VALIDATED=false\n')
    return value


def execution(env, scenario):
    if scenario == 'install':
        require(env.get('INSTALL_OUTCOME') == 'success' and
                env.get('AIRGAP_OUTCOME') == 'skipped', 'ordinary execution incomplete')
    else:
        require(env.get('INSTALL_OUTCOME') == 'skipped' and
                env.get('AIRGAP_OUTCOME') == 'success' and
                env.get('AIRGAP_RESTORE_OUTCOME') == 'success', 'airgap execution incomplete')
    require(env.get('SANITIZE_OK') == 'true', 'sanitization incomplete')


def command(root, args, env, seconds=15):
    # Limit only the output stream. RLIMIT_FSIZE would also cap legitimate
    # files unpacked by the SDK's local package inspection.
    process = subprocess.Popen(['timeout', '--kill-after=2s', f'{seconds}s', *args], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, start_new_session=True,
                               env={**env, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
                                    'FLAVOR': 'upstream'})
    deadline = time.monotonic() + seconds + 5
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'input command unavailable')
                if not selector.select(min(remaining, 1)):
                    continue
                chunk = os.read(process.stdout.fileno(), 1025 - len(output))
                if not chunk:
                    break
                output.extend(chunk)
                require(len(output) <= 1024, 'oversized input command output')
        require(process.wait(timeout=max(1, deadline - time.monotonic())) == 0,
                'input command unavailable')
        return output.decode().strip()
    finally:
        # The session is owned by this invocation; stop children too on timeout
        # or output overflow rather than leaving an inspection process running.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()


def pinned_inputs(root, env, arch):
    stage('pinned-key')
    key = command(root, ['bash', '.github/scripts/dev-package.sh', 'key'], env)
    require(re.fullmatch(arch + r'-[a-f0-9]{16}', key), 'invalid package key')
    stage('cli-version')
    version = command(root, ['uds', 'version'], env)
    # Read the actual CLI output, not a source pin or user-supplied version.
    match = re.fullmatch(r'v([0-9]+\.[0-9]+\.[0-9]+)', version)
    require(match is not None, 'unsupported UDS version output')
    return {'package_key': key, 'uds_version': match[1]}


def pinned(root, env, directory):
    stage('source-snapshot')
    saved = read_json(directory / 'install-source.json', 4096)
    require(saved == snapshot(root, env), 'checkout or run identity changed')
    value = pinned_inputs(root, env, saved['context']['arch'])
    stage('pinned-snapshot')
    with (directory / 'install-pinned.json').open('x') as output:
        json.dump(value, output, sort_keys=True)
        output.write('\n')
    return value


def collect(root, env, directory):
    stage('source-snapshot')
    saved = read_json(directory / 'install-source.json', 4096)
    require(saved == snapshot(root, env), 'checkout or run identity changed')
    ctx = saved['context']
    stage('execution')
    execution(env, ctx['scenario'])
    arch = ctx['arch']
    stage('pinned-snapshot')
    pinned = read_json(directory / 'install-pinned.json', 1024)
    actual_pinned = pinned_inputs(root, env, arch)
    stage('pinned-snapshot')
    require(pinned == actual_pinned, 'pinned inputs changed')
    stage('checkpoint-validation')
    require(env.get('INSTALL_RECEIPT_CHECKPOINT_VALIDATED') == 'true', 'checkpoint not validated')
    selected = read_json(directory / 'install-checkpoint-selection.json', 8192)
    require(isinstance(selected, dict) and set(selected) == {'archive', 'acquisition', 'run_id', 'attempt'} and
            selected['run_id'] == ctx['run_id'] and selected['attempt'] == ctx['attempt'],
            'checkpoint validation not from this run')
    archive = Path(selected['archive'])
    require(archive.resolve().parent == (root / '.cache/k3d-core-slim-dev').resolve(),
            'unsupported checkpoint path')
    acquisition = selected['acquisition']
    stage('checkpoint-archive')
    checkpoint.validate(acquisition, archive, acquisition.get('source'), acquisition.get('version'), arch)
    # This is the flavored archive actually built or pulled by create-dev-package.
    package = root / f'zarf-package-takserver-{arch}-dev-upstream.tar.zst'
    plain = root / f'zarf-package-takserver-{arch}-dev.tar.zst'
    stage('app-archive')
    package_hash = checkpoint.archive_hash(package)
    require(checkpoint.archive_hash(plain) == package_hash, 'bundled archive differs')
    stage('bundle-selection')
    bundles = [*root.glob(f'uds-bundle-takserver-dev-{arch}-dev.tar.zst'),
               *(root / 'bundle').glob(f'uds-bundle-takserver-dev-{arch}-dev.tar.zst')]
    require(len(bundles) == 1, 'ambiguous generated bundle')
    # Use the official SDK's deterministic local archive digest. Never resolve
    # an OCI tag or a cluster package as a substitute for these exact bytes.
    stage('local-package-oci')
    with tempfile.TemporaryDirectory(prefix='install-receipt-digest-', dir=directory) as temp:
        package_digest = command(root, ['uds', 'zarf', 'package', 'inspect', 'digest', str(package),
                                        '--tmpdir', temp], env, seconds=45)
    require(foundation.digest(package_digest), 'local package identity unavailable')
    stage('bundle-oci')
    derived = artifacts.identities(artifacts.metadata(bundles[0]), arch, package_digest)
    stage('app-archive-stability')
    require(checkpoint.archive_hash(package) == package_hash, 'package changed during collection')
    inputs = {**pinned, 'package_archive_sha256': package_hash,
              'checkpoint_oci_digest': acquisition['index_digest'],
              **derived}
    stage('receipt-write')
    result = foundation.receipt(root, REPOSITORY, ctx['event'], ctx['run_id'], ctx['attempt'],
                                arch, ctx['scenario'], 'success', inputs)
    require(result['source'] == {'repository': REPOSITORY, **saved['checkout']['source']} and
            result['workflow'] == saved['checkout']['workflow'], 'source identity changed')
    destination = directory / f"install-receipt-{ctx['scenario']}-{arch}.json"
    with destination.open('x') as output:
        json.dump(result, output, sort_keys=True)
        output.write('\n')
    with Path(env['GITHUB_OUTPUT']).open('a') as output:
        output.write(f'path={destination}\nready=true\n')
    return result


def main():
    stage('operation')
    try:
        require(sys.argv[1:] in (['capture'], ['pinned'], ['collect']), 'invalid operation')
        directory = Path(os.environ['RUNNER_TEMP'])
        if sys.argv[1] == 'capture':
            capture(ROOT, os.environ, directory)
        elif sys.argv[1] == 'pinned':
            pinned(ROOT, os.environ, directory)
        else:
            collect(ROOT, os.environ, directory)
        print('Optional install receipt evidence recorded')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError,
            subprocess.SubprocessError, tarfile.TarError):
        # Never echo arbitrary metadata, CLI stderr, paths, arguments or payloads.
        safe_stage = _omission_stage if _omission_stage in OMISSION_STAGES else 'operation'
        print('Optional install receipt omitted: stage=' + safe_stage)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
