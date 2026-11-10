#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Produce an install execution record; this never authorizes CI reuse."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

WORKFLOW = '.github/workflows/test.yaml'
GIT_TIMEOUT = 5
MAX_WORKFLOW_BYTES = 1024 * 1024
IMAGES = {'takserver-api', 'takserver-messaging', 'takserver-config',
          'takserver-plugins', 'takserver-database-setup', 'takserver-ignite',
          'cloudtak', 'postgis'}
INPUTS = {'package_key', 'package_archive_sha256', 'checkpoint_oci_digest', 'core_oci_digest',
          'image_digests', 'uds_version'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, names, label):
    require(isinstance(value, dict) and set(value) == names, f'invalid {label} fields')


def digest(value):
    return isinstance(value, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', value)


def validate_inputs(value, arch):
    fields(value, INPUTS, 'input identity')
    require(isinstance(value['package_key'], str) and
            re.fullmatch(arch + r'-[a-f0-9]{16}', value['package_key']), 'invalid package key')
    require(all(digest(value[name]) for name in
                ('package_archive_sha256', 'checkpoint_oci_digest', 'core_oci_digest')), 'invalid input digest')
    fields(value['image_digests'], IMAGES, 'image identity')
    require(all(digest(item) for item in value['image_digests'].values()), 'invalid image digest')
    require(isinstance(value['uds_version'], str) and
            re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value['uds_version']), 'invalid UDS version')
    return value


def git(root, *args):
    env = {**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'}
    try:
        result = subprocess.run(['git', '-c', 'protocol.allow=never', '--no-optional-locks',
                                 '-C', str(root), *args], capture_output=True, check=False,
                                timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('checkout identity unavailable') from None
    require(result.returncode == 0, 'checkout identity unavailable')
    return result.stdout


def receipt(root, repository, event, run_id, attempt, arch, scenario, result, inputs, mode='ordinary'):
    require(isinstance(repository, str) and
            re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}', repository), 'invalid repository')
    require(event in ('push', 'pull_request', 'workflow_dispatch'), 'unsupported event')
    require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0,
            'invalid run identity')
    require(mode == 'ordinary', 'unsupported validation mode')
    require(arch in ('amd64', 'arm64'), 'unsupported architecture')
    require(scenario in ('install', 'install-airgap') and
            (scenario != 'install-airgap' or arch == 'amd64'), 'unsupported install scenario')
    require(result == 'success', 'install execution did not succeed')
    inputs = validate_inputs(inputs, arch)
    commit = git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    tree = git(root, 'rev-parse', '--verify', 'HEAD^{tree}').decode().strip()
    require(all(re.fullmatch(r'[a-f0-9]{40}', item) for item in (commit, tree)),
            'unsupported checkout identity')
    size = git(root, 'cat-file', '-s', f'HEAD:{WORKFLOW}').strip()
    require(size.isdigit() and int(size) <= MAX_WORKFLOW_BYTES, 'workflow identity unavailable')
    workflow = git(root, 'show', f'HEAD:{WORKFLOW}')
    return {
        'schema_version': 1,
        'kind': 'install-execution',
        'reuse_authorized': False,
        'source': {'repository': repository, 'checkout_commit': commit, 'checkout_tree': tree},
        'workflow': {'path': WORKFLOW, 'sha256': hashlib.sha256(workflow).hexdigest()},
        'run': {'id': run_id, 'attempt': attempt, 'event': event, 'job': 'validate-install'},
        'scenario': {'name': scenario, 'architecture': arch, 'mode': mode},
        'execution': {'step': 'Test' if scenario == 'install' else
                      'Install and test without node internet egress', 'result': result},
        'inputs': inputs,
    }


class OmissionParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Install receipt omitted: invalid arguments\n')


def main():
    parser = OmissionParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, default=Path('.'))
    parser.add_argument('--repository', required=True)
    parser.add_argument('--event', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--attempt', type=int, required=True)
    parser.add_argument('--architecture', required=True)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--execution-result', required=True)
    parser.add_argument('--mode', default='ordinary')
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Bound and validate the explicitly curated manifest. Never read/dump env,
    # kubeconfig, rendered values, credentials or arbitrary context JSON.
    require(args.inputs.stat().st_size <= 16384, 'input manifest is too large')
    inputs = json.loads(args.inputs.read_text(encoding='utf-8'))
    value = receipt(args.checkout, args.repository, args.event, args.run_id, args.attempt,
                    args.architecture, args.scenario, args.execution_result, inputs, args.mode)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print('Install execution receipt written; reuse is not authorized.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, UnicodeError):
        # Rejected payloads and exception messages can contain credentials.
        raise SystemExit('Install receipt omitted: invalid or unavailable evidence') from None
