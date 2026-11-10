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
import resource
import subprocess
import sys
import tarfile
import tempfile

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


def read_json(path, limit):
    require(path.stat().st_size <= limit, 'oversized evidence')
    return json.loads(path.read_bytes())


def context(env):
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
    return {'context': context(env), 'checkout': foundation.checkout_identity(root)}


def capture(root, env, directory):
    value = snapshot(root, env)
    with (directory / 'install-source.json').open('x') as output:
        json.dump(value, output, sort_keys=True)
        output.write('\n')
    # This option only records acquisition metadata. It cannot skip work.
    with Path(env['GITHUB_ENV']).open('a') as output:
        output.write('INSTALL_RECEIPT_METADATA=true\n')
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


def command(root, args, env):
    def limit_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(['timeout', '--kill-after=2s', '15s', *args], cwd=root,
                                stdout=output, stderr=subprocess.DEVNULL, timeout=20,
                                stdin=subprocess.DEVNULL, check=False, preexec_fn=limit_output,
                                env={**env, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
                                     'FLAVOR': 'upstream'})
        require(result.returncode == 0, 'input command unavailable')
        output.seek(0)
        return output.read(1024).decode().strip()


def pinned_inputs(root, env, arch):
    key = command(root, ['bash', '.github/scripts/dev-package.sh', 'key'], env)
    require(re.fullmatch(arch + r'-[a-f0-9]{16}', key), 'invalid package key')
    version = command(root, ['uds', 'version'], env)
    # Read the actual CLI output, not a source pin or user-supplied version.
    match = re.fullmatch(r'v([0-9]+\.[0-9]+\.[0-9]+)', version)
    require(match is not None, 'unsupported UDS version output')
    return {'package_key': key, 'uds_version': match[1]}


def pinned(root, env, directory):
    saved = read_json(directory / 'install-source.json', 4096)
    require(saved == snapshot(root, env), 'checkout or run identity changed')
    value = pinned_inputs(root, env, saved['context']['arch'])
    with (directory / 'install-pinned.json').open('x') as output:
        json.dump(value, output, sort_keys=True)
        output.write('\n')
    return value


def collect(root, env, directory):
    saved = read_json(directory / 'install-source.json', 4096)
    require(saved == snapshot(root, env), 'checkout or run identity changed')
    ctx = saved['context']
    execution(env, ctx['scenario'])
    arch = ctx['arch']
    pinned = read_json(directory / 'install-pinned.json', 1024)
    require(pinned == pinned_inputs(root, env, arch), 'pinned inputs changed')
    archives = list((root / '.cache/k3d-core-slim-dev').glob(
        f'zarf-package-k3d-core-slim-dev-{arch}-*.tar.zst'))
    require(len(archives) == 1, 'ambiguous checkpoint')
    archive = archives[0]
    acquisition = read_json(Path(str(archive) + '.receipt.json'), 4096)
    checkpoint.validate(acquisition, archive, acquisition.get('source'), acquisition.get('version'), arch)
    # This is the flavored archive actually built or pulled by create-dev-package.
    package = root / f'zarf-package-takserver-{arch}-dev-upstream.tar.zst'
    plain = root / f'zarf-package-takserver-{arch}-dev.tar.zst'
    package_hash = checkpoint.archive_hash(package)
    require(checkpoint.archive_hash(plain) == package_hash, 'bundled archive differs')
    bundles = [*root.glob(f'uds-bundle-takserver-dev-{arch}-dev.tar.zst'),
               *(root / 'bundle').glob(f'uds-bundle-takserver-dev-{arch}-dev.tar.zst')]
    require(len(bundles) == 1, 'ambiguous generated bundle')
    derived = artifacts.identities(artifacts.metadata(bundles[0]), arch)
    inputs = {**pinned, 'package_archive_sha256': package_hash,
              'checkpoint_oci_digest': acquisition['index_digest'],
              **derived}
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
        print('Optional install receipt omitted: complete evidence unavailable')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
