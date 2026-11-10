#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Guarded metadata steps for the disposable Velero ownership experiment.

This deliberately does not run Helm or UDS deployments: the staged orchestrator
must interleave these guarded steps with reviewed signed bundle deployments and
readiness/backup observations. No default installation behavior changes.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import yaml

SPEC = importlib.util.spec_from_file_location('ephemeral_cluster', Path(__file__).parents[1] / 'ephemeral-cluster.py')
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
LOCAL = ('uds-takserver-config', 'takserver')
CORE = ('velero', 'velero')
PAYLOAD = {'privilegedFsBackup': True, 'podLabels': {
    'app.kubernetes.io/name': 'velero', 'app.kubernetes.io/component': 'velero-data-mover'}}
TERMINAL = {
    'backups.velero.io': {'Completed', 'Failed', 'PartiallyFailed', 'FailedValidation'},
    'restores.velero.io': {'Completed', 'Failed', 'PartiallyFailed', 'FailedValidation'},
    'podvolumebackups.velero.io': {'Completed', 'Failed'},
    'podvolumerestores.velero.io': {'Completed', 'Failed'},
    'datauploads.velero.io': {'Completed', 'Failed', 'Canceled'},
    'datadownloads.velero.io': {'Completed', 'Failed', 'Canceled'},
}


def require(value, message):
    if not value:
        raise ValueError(message)


def ownership(obj):
    meta = obj['metadata']
    return (meta.get('annotations', {}).get('meta.helm.sh/release-name'),
            meta.get('annotations', {}).get('meta.helm.sh/release-namespace'))


def validate_agent(ds, expected_uid, expected_owner, ready=True):
    meta = ds['metadata']
    require(meta.get('name') == 'node-agent' and meta.get('namespace') == 'velero'
            and meta.get('uid') == expected_uid and meta.get('resourceVersion')
            and not meta.get('deletionTimestamp'), 'agent identity changed or is terminating')
    require(ownership(ds) == expected_owner and meta.get('labels', {}).get('app.kubernetes.io/managed-by') == 'Helm',
            'agent has an unexpected owner')
    require(ds['spec']['selector'] == {'matchLabels': {'name': 'node-agent'}}, 'agent selector differs')
    if ready:
        status = ds.get('status', {})
        desired = status.get('desiredNumberScheduled', 0)
        require(desired > 0 and status.get('numberReady') == desired
                and status.get('numberAvailable') == desired and status.get('updatedNumberScheduled') == desired
                and status.get('numberUnavailable', 0) == 0
                and status.get('observedGeneration', 0) >= meta.get('generation', 1), 'agent is not fully Ready')


def ownership_patch(ds, expected_uid, source, target):
    """JSON Patch CAS: any concurrent controller/owner update rejects the write."""
    validate_agent(ds, expected_uid, source)
    meta = ds['metadata']
    patch = [
        {'op': 'test', 'path': '/metadata/uid', 'value': expected_uid},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']},
        {'op': 'test', 'path': '/metadata/annotations/meta.helm.sh~1release-name', 'value': source[0]},
        {'op': 'test', 'path': '/metadata/annotations/meta.helm.sh~1release-namespace', 'value': source[1]},
        {'op': 'test', 'path': '/metadata/labels/app.kubernetes.io~1managed-by', 'value': 'Helm'},
        {'op': 'add', 'path': '/metadata/annotations/helm.sh~1resource-policy', 'value': 'keep'},
    ]
    if source != target:
        patch += [
            {'op': 'replace', 'path': '/metadata/annotations/meta.helm.sh~1release-name', 'value': target[0]},
            {'op': 'replace', 'path': '/metadata/annotations/meta.helm.sh~1release-namespace', 'value': target[1]},
        ]
    return patch


def validate_idle(objects):
    for kind, phases in TERMINAL.items():
        for obj in objects[kind]['items']:
            require(not obj['metadata'].get('deletionTimestamp') and obj.get('status', {}).get('phase') in phases,
                    'Velero work is active, terminating or has an unknown phase: ' + kind)
    for obj in objects['schedules.velero.io']['items']:
        require(obj.get('spec', {}).get('paused') is True and not obj['metadata'].get('deletionTimestamp'),
                'Velero schedules must be explicitly paused')
    for pod in objects['pods']['items']:
        labels = pod['metadata'].get('labels', {})
        mover = (labels.get('app.kubernetes.io/component') == 'velero-data-mover'
                 or any(key.startswith(('velero.io/pod-volume-', 'velero.io/data-upload', 'velero.io/data-download')) for key in labels))
        require(not mover or (not pod['metadata'].get('deletionTimestamp')
                              and pod.get('status', {}).get('phase') in ('Succeeded', 'Failed')),
                'a data-mover pod is active or terminating')


class Transfer:
    def __init__(self, context, uid, command, guard=GUARD.verify):
        self.context, self.uid, self.command, self.guard = context, uid, command, guard
        self.identity = guard(context, command)

    def read(self, kind, name=None):
        args = ['kubectl', '--context', self.context, 'get', kind]
        if name:
            args.append(name)
        args += ['-n', 'velero', '-o', 'json']
        return json.loads(self.command(args))

    def before_write(self):
        identity = self.guard(self.context, self.command)
        require(identity == self.identity, 'ephemeral cluster receipt changed')
        validate_idle({kind: self.read(kind) for kind in (*TERMINAL, 'schedules.velero.io', 'pods')})

    def recorded_agent(self, release):
        text = self.command(['uds', 'zarf', 'tools', 'helm', '--kube-context', self.context,
                             'get', 'manifest', release[0], '-n', release[1]])
        # Release manifests may contain secrets; keep only the boolean in memory.
        return any(obj and obj.get('kind') == 'DaemonSet'
                   and obj.get('metadata', {}).get('name') == 'node-agent'
                   and obj.get('metadata', {}).get('namespace') == 'velero'
                   for obj in yaml.safe_load_all(text))

    def check_config(self, owner):
        name = 'node-agent-config' if owner == LOCAL else 'velero-node-agent-config'
        obj = self.read('configmap', name)
        meta = obj.get('metadata', {})
        require(meta.get('name') == name and meta.get('namespace') == 'velero'
                and meta.get('uid') and meta.get('resourceVersion') and not meta.get('deletionTimestamp')
                and ownership(obj) == owner and meta.get('labels', {}).get('app.kubernetes.io/managed-by') == 'Helm'
                and json.loads(obj.get('data', {}).get('node-agent-config.json', 'null')) == PAYLOAD,
                'source agent configuration has changed, is incomplete or has an unknown owner')

    def transfer(self, source, target):
        self.before_write()
        ds = self.read('daemonset', 'node-agent')
        # Idempotence is based on actual API state, not a prior success journal.
        if source != target and ownership(ds) == target:
            validate_agent(ds, self.uid, target)
            require(ds['metadata']['annotations'].get('helm.sh/resource-policy') == 'keep', 'transferred agent lacks keep')
            return {'changed': False, 'uid': self.uid, 'resourceVersion': ds['metadata']['resourceVersion']}
        if source != target:
            require(not self.recorded_agent(CORE), 'Core still records the agent; detach it with desired keep first')
            require(self.recorded_agent(LOCAL) == (source == LOCAL),
                    'local release manifest does not match the staged transfer boundary')
        self.check_config(source)
        if source == CORE:
            require(ds['metadata'].get('annotations', {}).get('helm.sh/resource-policy') == 'keep',
                    'Core source agent lacks prior keep protection')
        patch = ownership_patch(ds, self.uid, source, target)
        # Recheck run/cluster immediately before the guarded write as idle reads take time.
        require(self.guard(self.context, self.command) == self.identity, 'ephemeral cluster receipt changed')
        self.command(['kubectl', '--context', self.context, 'patch', 'daemonset', 'node-agent', '-n', 'velero',
                      '--type=json', '--patch-file=/dev/stdin', '-o', 'json'], json.dumps(patch))
        actual = self.read('daemonset', 'node-agent')
        validate_agent(actual, self.uid, target)
        require(actual['metadata']['annotations'].get('helm.sh/resource-policy') == 'keep', 'keep patch not retained')
        return {'changed': True, 'uid': self.uid, 'resourceVersion': actual['metadata']['resourceVersion']}

    def local_config(self):
        self.before_write()
        # Must be Core-owned, protected, and ready before a reversal prepares local config.
        ds = self.read('daemonset', 'node-agent')
        validate_agent(ds, self.uid, CORE)
        require(ds['metadata'].get('annotations', {}).get('helm.sh/resource-policy') == 'keep', 'Core agent is not protected')
        text = self.command(['kubectl', '--context', self.context, 'get', 'configmap', 'node-agent-config',
                             '-n', 'velero', '--ignore-not-found', '-o', 'json'])
        if text.strip():
            obj = json.loads(text)
            require(ownership(obj) == LOCAL and not obj['metadata'].get('deletionTimestamp')
                    and obj['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') == 'Helm'
                    and json.loads(obj.get('data', {}).get('node-agent-config.json', 'null')) == PAYLOAD,
                    'existing local config is not the expected nonterminating Helm object')
            return {'changed': False, 'uid': obj['metadata']['uid']}
        obj = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
            'name': 'node-agent-config', 'namespace': 'velero',
            'annotations': {'meta.helm.sh/release-name': LOCAL[0], 'meta.helm.sh/release-namespace': LOCAL[1]},
            'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
            'data': {'node-agent-config.json': json.dumps(PAYLOAD, separators=(',', ':'))}}
        require(self.guard(self.context, self.command) == self.identity, 'ephemeral cluster receipt changed')
        result = json.loads(self.command(['kubectl', '--context', self.context, 'create', '-f', '-', '-o', 'json'], json.dumps(obj)))
        require(result.get('metadata', {}).get('uid'), 'API did not return created config identity')
        return {'changed': True, 'uid': result['metadata']['uid']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('protect-local', 'to-core', 'prepare-local-config', 'to-local'))
    parser.add_argument('--context', choices=(GUARD.CONTEXT,), required=True)
    parser.add_argument('--daemonset-uid', required=True)
    args = parser.parse_args()

    def command(argv, input_text=None):
        result = subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=45)
        require(result.returncode == 0, 'guarded API command failed; no automatic rollback attempted')
        return result.stdout

    transfer = Transfer(args.context, args.daemonset_uid, command)
    if args.operation == 'prepare-local-config':
        receipt = transfer.local_config()
    else:
        source, target = {'protect-local': (LOCAL, LOCAL), 'to-core': (LOCAL, CORE), 'to-local': (CORE, LOCAL)}[args.operation]
        receipt = transfer.transfer(source, target)
    print(json.dumps({'operation': args.operation, 'cluster': transfer.identity, 'resource': receipt}, indent=2))


if __name__ == '__main__':
    main()
