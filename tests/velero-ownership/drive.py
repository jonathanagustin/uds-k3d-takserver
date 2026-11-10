#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in disposable-cluster Velero fresh/handoff/reversal acceptance driver.

Consumes reviewed, separately assembled UDS bundles with Core keyless checks. A failure stops in
place, preserves a private journal, and never triggers an automatic rollback.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('velero_transfer', Path(__file__).with_name('transfer.py'))
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)
require = T.require


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load_plan(path):
    """Only fixed deployment inputs, no arbitrary commands or flag injection."""
    require(path.is_file() and not path.is_symlink(), 'plan must be a regular local file')
    plan = json.loads(path.read_text())
    require(set(plan) == {'schema', 'sourceSHA', 'files'} and plan['schema'] == 1
            and plan['sourceSHA'] == os.environ.get('GITHUB_SHA'), 'plan source differs from workflow source')
    require(set(plan['files']) == {'core', 'detach', 'clean', 'config'}, 'plan must bind the four reviewed inputs')
    files = {}
    for key, entry in plan['files'].items():
        require(set(entry) == {'path', 'sha256'}, 'unexpected plan input fields')
        relative = Path(entry['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'plan input escapes its directory')
        target = path.parent / relative
        require(not any(p.is_symlink() for p in [target, *target.parents]) and target.is_file(), 'plan inputs must be regular files')
        require(digest(target) == entry['sha256'], 'plan input checksum differs: ' + key)
        files[key] = target.resolve()
    config = yaml.safe_load(files['config'].read_text())
    require(isinstance(config, dict) and set(config) == {'variables'}
            and set(config['variables']) == {'takserver'}, 'config must contain only reviewed TAK variables')
    values = config['variables']['takserver']
    require(set(values) == {'DOMAIN', 'TAK_IMAGE_TAG', 'FILESYSTEM_BACKUP', 'POSTGRES_STORAGE_CLASS', 'CLOUDTAK_STORAGE_CLASS'}
            and values['DOMAIN'] == 'uds.dev' and str(values['FILESYSTEM_BACKUP']).lower() == 'true'
            and values['POSTGRES_STORAGE_CLASS'] == values['CLOUDTAK_STORAGE_CLASS'] == 'local-path-local',
            'trial requires filesystem backup and both real local volumes; no extra config options')
    return files


class Driver:
    def __init__(self, files, directory, execute, context=T.GUARD.CONTEXT):
        self.files, self.directory, self.execute, self.context = files, directory, execute, context
        self.identity = T.GUARD.verify(context, self.read_command)
        self.transfer = T.Transfer(context, '', self.read_command)
        self.state = {'schema': 1, 'cluster': self.identity, 'driverSHA256': digest(Path(__file__)),
                      'inputs': {key: digest(value) for key, value in files.items()}, 'steps': [], 'accepted': False}

    def read_command(self, argv, input_text=None):
        return self.execute(argv, input_text=input_text, timeout=45)

    def guarded(self):
        require(T.GUARD.verify(self.context, self.read_command) == self.identity, 'ephemeral identity changed')

    def journal(self):
        temporary = self.directory / 'journal.pending'
        with temporary.open('w') as stream:
            json.dump(self.state, stream, indent=2)
            stream.write('\n')
        temporary.chmod(0o600)
        temporary.replace(self.directory / 'journal.json')

    def step(self, name, action):
        self.guarded()
        record = {'name': name, 'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'status': 'running'}
        self.state['steps'].append(record)
        self.journal()
        try:
            action()
            record['status'] = 'passed'
        except Exception:
            # Do not publish exception text: a subprocess error may carry credentials.
            record['status'] = 'failed'
            try:
                current = self.transfer.read('daemonset', 'node-agent')
                meta = current.get('metadata', {})
                record['agentAtFailure'] = {'uid': meta.get('uid'), 'resourceVersion': meta.get('resourceVersion'),
                                            'owner': list(T.ownership(current)), 'terminating': bool(meta.get('deletionTimestamp'))}
            except Exception:
                record['agentAtFailure'] = 'unavailable; no identity inferred'
            self.journal()
            raise
        self.journal()

    def idle(self):
        self.guarded()
        T.validate_idle({kind: self.transfer.read(kind) for kind in (*T.TERMINAL, 'schedules.velero.io', 'pods')})

    def deploy(self, bundle, package, owner=None, bootstrap=False):
        if bootstrap:
            self.guarded()
        else:
            self.idle()
        # Rehash immediately before use. Never resume an arbitrary prior deployment.
        require(digest(self.files[bundle]) == self.state['inputs'][bundle]
                and digest(self.files['config']) == self.state['inputs']['config'], 'deployment input changed')
        args = ['uds', 'deploy', str(self.files[bundle]), '--packages', package,
                '--confirm', '--retries', '1', '--no-progress', '--no-log-file']
        if owner:
            args += ['--set', 'takserver.FILESSYSTEM_BACKUP_OWNER=' + owner]
        self.guarded()
        self.execute(args, timeout=1500, env={'UDS_CONFIG': str(self.files['config'])})

    def wait(self):
        self.guarded()
        self.execute(['kubectl', '--context', self.context, 'rollout', 'status', 'daemonset/node-agent',
                      '-n', 'velero', '--timeout=600s'], timeout=630)
        ds = self.transfer.read('daemonset', 'node-agent')
        require(ds['metadata']['uid'] == self.transfer.uid, 'agent UID changed during deployment')

    def observe(self, stage, group, backup=None):
        args = [sys.executable, str(Path(__file__).with_name('observe.py')), '--context', self.context,
                '--directory', str(self.directory / group), '--stage', stage]
        if backup:
            args += ['--backup', backup, '--restore', backup + '-r']
        self.guarded()
        self.execute(args, timeout=360)

    def accept(self, stage, group, suffix):
        self.idle()
        self.guarded()
        self.execute(['bash', str(ROOT / 'tests/backup-restore.sh')], timeout=2100,
                     env={'REQUIRE_FS_BACKUP': 'true', 'BACKUP_TRIAL_SUFFIX': suffix, 'BACKUP_TRIAL_CONTEXT': self.context})
        backup = 'tak-ci-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'] + '-' + suffix
        self.observe(stage, group, backup)

    def reverse(self):
        ds = self.transfer.read('daemonset', 'node-agent')
        T.validate_agent(ds, self.transfer.uid, T.ownership(ds))
        require(T.ownership(ds) in (T.CORE, T.LOCAL), 'recovery found an unknown owner')
        if T.ownership(ds) == T.CORE:
            self.step('prepare-local-config', self.transfer.local_config)
            self.step('detach-core-agent-retain-config', lambda: self.deploy('detach', 'core-backup-restore'))
            self.step('transfer-to-local', lambda: self.transfer.transfer(T.CORE, T.LOCAL))
        else:
            require(not self.transfer.recorded_agent(T.CORE), 'local recovery found a conflicting Core manifest')
        # Local owner can be an interrupted metadata handoff. Reapply the real
        # package; never infer a successful rollout from owner annotations.
        self.step('deploy-local-agent', lambda: self.deploy('core', 'takserver', 'local'))
        self.step('wait-local-agent', self.wait)
        self.step('retire-core-config', lambda: self.deploy('clean', 'core-backup-restore'))

    def round_trip(self):
        # A truly fresh Core-owner installation, not a local agent renamed Core.
        existing = self.read_command(['kubectl', '--context', self.context, 'get', 'daemonset', 'node-agent',
                                      '-n', 'velero', '--ignore-not-found', '-o', 'json'])
        require(not existing.strip(), 'fresh trial requires no existing agent')
        server = self.read_command(['kubectl', '--context', self.context, 'get', 'deployment', 'velero',
                                    '-n', 'velero', '--ignore-not-found', '-o', 'json'])
        require(not server.strip(), 'fresh trial requires no existing Velero server')
        self.step('bootstrap-exemption', lambda: self.deploy('core', 'core-base', bootstrap=True))
        self.step('fresh-core-agent', lambda: self.deploy('core', 'core-backup-restore', bootstrap=True))
        ds = self.transfer.read('daemonset', 'node-agent')
        self.transfer.uid = ds['metadata']['uid']
        self.state['daemonsetUID'] = self.transfer.uid
        self.journal()
        self.step('fresh-core-app', lambda: self.deploy('core', 'takserver', 'core'))
        self.step('wait-fresh-agent', self.wait)
        self.step('fresh-ready', lambda: self.observe('fresh-ready', 'fresh'))
        self.step('fresh-acceptance', lambda: self.accept('fresh-core', 'fresh', 'fresh'))
        # Establish a known local baseline on the same owned cluster; this
        # bootstrap reversal is not counted as the later accepted round-trip.
        self.reverse()
        self.step('local-before', lambda: self.observe('local-before', 'handoff'))
        self.step('protect-local-agent', lambda: self.transfer.transfer(T.LOCAL, T.LOCAL))
        self.step('transfer-to-core', lambda: self.transfer.transfer(T.LOCAL, T.CORE))
        self.step('deploy-core-agent', lambda: self.deploy('core', 'core-backup-restore'))
        self.step('detach-local-agent', lambda: self.deploy('core', 'takserver', 'core'))
        self.step('wait-core-agent', self.wait)
        self.step('core-ready', lambda: self.observe('core-ready', 'handoff'))
        self.step('core-acceptance', lambda: self.accept('core-after', 'handoff', 'core'))
        self.reverse()
        self.step('local-ready', lambda: self.observe('local-ready', 'handoff'))
        self.step('local-acceptance', lambda: self.accept('local-after', 'handoff', 'local'))
        self.state['accepted'] = True
        self.journal()


def runner(argv, input_text=None, timeout=45, env=None, diagnostics=None):
    child = subprocess.Popen(argv, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                             cwd=ROOT, env={**os.environ, **(env or {})})
    try:
        stdout, stderr = child.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            stdout, stderr = child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            stdout, stderr = child.communicate()
        if diagnostics:
            diagnostics.write_text((stdout + '\n' + stderr)[-65536:])
            diagnostics.chmod(0o600)
        raise ValueError('staged command timed out; inspect private stage evidence before recovery') from None
    if child.returncode and diagnostics:
        diagnostics.write_text((stdout + '\n' + stderr)[-65536:])
        diagnostics.chmod(0o600)
    require(child.returncode == 0, 'staged command failed; no automatic rollback attempted')
    return stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('round-trip', 'recover-local'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--daemonset-uid', help='required only for explicit recovery; take from the original journal')
    args = parser.parse_args()
    files = load_plan(args.plan.resolve())
    require(not args.evidence.exists(), 'use a new private evidence directory; previous journals are never overwritten')
    args.evidence.mkdir(parents=True, mode=0o700)
    def execute(argv, **kwargs):
        return runner(argv, diagnostics=args.evidence / 'PRIVATE-command-failure.txt', **kwargs)

    driver = Driver(files, args.evidence, execute)
    if args.operation == 'recover-local':
        require(args.daemonset_uid, 'recovery requires original DaemonSet UID')
        driver.transfer.uid = args.daemonset_uid
        driver.state['recoveryOnly'] = True
        driver.reverse()
        driver.journal()
    else:
        require(not args.daemonset_uid, 'fresh trial must discover its own agent UID')
        driver.round_trip()
    print(json.dumps({'accepted': driver.state['accepted'], 'journal': str(args.evidence / 'journal.json')}))


if __name__ == '__main__':
    main()
