#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only, bounded observations of a separately operated Velero handoff.

Never patches ownership, upgrades a release, deletes objects, or runs a restore.
"""
import argparse
import datetime
import json
import hashlib
from pathlib import Path
import subprocess
import yaml

LOCAL = ('uds-takserver-config', 'takserver')
CORE = ('velero', 'velero')


def require(value, message):
    if not value:
        raise ValueError(message)


def owner(obj, expected):
    meta = obj['metadata']
    return (meta.get('annotations', {}).get('meta.helm.sh/release-name'),
            meta.get('annotations', {}).get('meta.helm.sh/release-namespace')) == expected and meta.get('labels', {}).get('app.kubernetes.io/managed-by') == 'Helm'


def resources(text):
    # Never retain complete release manifests, which can contain Secret data.
    return [d for d in yaml.safe_load_all(text) if d and
            d.get('metadata', {}).get('namespace') == 'velero' and
            (d.get('kind'), d['metadata']['name']) in {
                ('DaemonSet', 'node-agent'), ('ConfigMap', 'node-agent-config'),
                ('ConfigMap', 'velero-node-agent-config')}]


def validate(snapshot, stage, baseline=None):
    ds = snapshot['daemonset']
    require(not ds['metadata'].get('deletionTimestamp'), 'agent DaemonSet is terminating')
    require(ds['spec']['selector'] == {'matchLabels': {'name': 'node-agent'}}, 'unexpected immutable selector')
    uid = ds['metadata']['uid']
    if baseline:
        require(snapshot['clusterUID'] == baseline['clusterUID'], 'cluster changed')
        require(uid == baseline['daemonsetUID'], 'DaemonSet was replaced')
    expected = LOCAL if stage in ('local-before', 'local-ready', 'local-after') else CORE
    require(owner(ds, expected), 'unknown or unexpected release owner')
    desired = ds['status'].get('desiredNumberScheduled', 0)
    require(desired > 0 and ds['status'].get('numberReady') == desired and
            ds['status'].get('updatedNumberScheduled') == desired and
            ds['status'].get('numberAvailable') == desired and
            ds['status'].get('numberUnavailable', 0) == 0 and
            ds['status'].get('observedGeneration', 0) >= ds['metadata']['generation'], 'agent rollout is not fully Ready')
    pods = snapshot['pods']['items']
    require(len(pods) == desired, 'agent pod count differs from desired nodes')
    config = 'node-agent-config' if expected == LOCAL else 'velero-node-agent-config'
    for pod in pods:
        require(not pod['metadata'].get('deletionTimestamp'), 'agent pod is terminating')
        require(any(o.get('uid') == uid and o.get('controller') is True for o in pod['metadata'].get('ownerReferences', [])), 'pod is not controlled by this DaemonSet')
        require(pod['status'].get('phase') == 'Running' and any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in pod['status'].get('conditions', [])), 'agent pod not Ready')
        container = next(c for c in pod['spec']['containers'] if c['name'] == 'node-agent')
        require('--node-agent-configmap=' + config in container.get('args', []), 'pod uses wrong agent configuration')
    require(snapshot['agentConfig']['metadata']['name'] == config and owner(snapshot['agentConfig'], expected), 'configuration has wrong name/owner')
    require(not snapshot['agentConfig']['metadata'].get('deletionTimestamp'), 'agent configuration is terminating')
    payload = json.loads(snapshot['agentConfig']['data']['node-agent-config.json'])
    require(payload == {'privilegedFsBackup': True, 'podLabels': {'app.kubernetes.io/name': 'velero', 'app.kubernetes.io/component': 'velero-data-mover'}}, 'unexpected data-mover configuration')
    require(snapshot['bootstrap']['metadata']['name'] == 'velero-node-agent-bootstrap' and snapshot['localExemption']['metadata']['name'] == 'velero-node-agent', 'unexpected exemption identities')
    require(snapshot['bootstrap']['spec'] == snapshot['localExemption']['spec'], 'bootstrap exemption differs from local policy')
    def has(release, kind, name):
        return any(d['kind'] == kind and d['metadata']['name'] == name for d in snapshot[release])
    if expected == CORE:
        require(has('coreManifest', 'DaemonSet', 'node-agent') and has('coreManifest', 'ConfigMap', config), 'Core manifest lacks actual agent/config')
        require(not has('localManifest', 'DaemonSet', 'node-agent') and not has('localManifest', 'ConfigMap', 'node-agent-config'), 'old release still records agent/config')
        require(ds['metadata'].get('annotations', {}).get('helm.sh/resource-policy') == 'keep', 'handoff protection missing')
        manifest_ds = next(d for d in snapshot['coreManifest'] if d['kind'] == 'DaemonSet')
        require(manifest_ds['metadata'].get('annotations', {}).get('helm.sh/resource-policy') == 'keep', 'Core desired keep annotation missing')
    else:
        require(has('localManifest', 'DaemonSet', 'node-agent') and has('localManifest', 'ConfigMap', config), 'local manifest lacks agent/config')
        require(not has('coreManifest', 'DaemonSet', 'node-agent'), 'Core still records the agent')
        require(not has('coreManifest', 'ConfigMap', 'velero-node-agent-config'), 'Core still records retired agent configuration')
        require('retiredCoreConfig' in snapshot and snapshot['retiredCoreConfig'] is None, 'retired Core configuration still exists or absence was not observed')
    acceptance = stage in ('core-after', 'local-after', 'fresh-core')
    if acceptance:
        backup, restore = snapshot['backup'], snapshot['restore']
        def timestamp(value):
            return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(timestamp(backup['metadata']['creationTimestamp']) >= timestamp(snapshot['readyAt']), 'backup predates accepted owner readiness')
        require(restore['spec']['backupName'] == backup['metadata']['name'], 'restore uses another backup')
        for obj in (backup, restore):
            require(obj['status'].get('phase') == 'Completed' and obj['status'].get('errors', 0) == 0 and obj['status'].get('warnings', 0) == 0 and not obj['status'].get('failureReason'), 'backup/restore not cleanly Completed')
        for key, label, name in [('pvb', 'velero.io/backup-name', backup['metadata']['name']), ('pvr', 'velero.io/restore-name', restore['metadata']['name'])]:
            items = snapshot[key]['items']
            require(items and all(v['status'].get('phase') == 'Completed' for v in items), 'volume copies not all Completed')
            for namespace in ('takserver', 'cloudtak'):
                require(any(v['metadata'].get('labels', {}).get(label) == name and v['spec']['pod']['namespace'] == namespace and v['spec']['volume'] == 'data' for v in items), 'missing completed database data volume for ' + namespace)
    return {'schema': 1, 'observerSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'clusterUID': snapshot['clusterUID'], 'daemonsetUID': uid, 'stage': stage,
            'observedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'backupRestore': acceptance, 'retiredCoreConfigAbsent': expected == LOCAL, 'postRestoreApiSmoke': 'separate required full-core test; not asserted here'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--stage', choices=['local-before', 'core-ready', 'core-after', 'local-ready', 'local-after', 'fresh-ready', 'fresh-core'], required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--backup')
    parser.add_argument('--restore')
    args = parser.parse_args()
    acceptance = args.stage in ('core-after', 'local-after', 'fresh-core')
    require(not acceptance or (args.backup and args.restore), 'backup and restore names required')
    baseline = None
    if args.stage in ('core-ready', 'core-after', 'local-ready', 'local-after'):
        baseline = json.loads((args.directory / 'local-before.json').read_text())
        require(baseline.get('schema') == 1 and baseline.get('stage') == 'local-before' and baseline.get('observerSHA256') == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'unknown or changed baseline proof')
    if args.stage in ('local-ready', 'local-after'):
        forward = json.loads((args.directory / 'core-after.json').read_text())
        require(forward.get('schema') == 1 and forward.get('stage') == 'core-after' and forward.get('backupRestore') is True and forward.get('clusterUID') == baseline['clusterUID'] and forward.get('daemonsetUID') == baseline['daemonsetUID'] and forward.get('observerSHA256') == baseline['observerSHA256'], 'valid same-cluster forward acceptance must precede reversal')
    def command(argv):
        result = subprocess.run(argv, text=True, capture_output=True, timeout=45)
        require(result.returncode == 0, 'read-only observation command failed')
        return result.stdout
    def get(kind, name=None, namespace='velero', selector=None):
        argv = ['kubectl', '--context', args.context, 'get', kind]
        if name: argv.append(name)
        argv += ['-n', namespace, '-o', 'json']
        if selector: argv += ['-l', selector]
        return json.loads(command(argv))
    ds = get('daemonset', 'node-agent')
    local = args.stage in ('local-before', 'local-ready', 'local-after')
    snapshot = {'clusterUID': get('namespace', 'kube-system', 'default')['metadata']['uid'],
                'daemonset': ds, 'pods': get('pods', selector='name=node-agent'),
                'agentConfig': get('configmap', 'node-agent-config' if local else 'velero-node-agent-config'),
                'bootstrap': get('exemption', 'velero-node-agent-bootstrap', 'uds-policy-exemptions'),
                'localExemption': get('exemption', 'velero-node-agent', 'uds-policy-exemptions')}
    if local:
        retired = command(['kubectl', '--context', args.context, 'get', 'configmap', 'velero-node-agent-config',
                           '-n', 'velero', '--ignore-not-found', '-o', 'json'])
        snapshot['retiredCoreConfig'] = json.loads(retired) if retired.strip() else None
    for key, release in [('localManifest', LOCAL), ('coreManifest', CORE)]:
        snapshot[key] = resources(command(['helm', '--kube-context', args.context, 'get', 'manifest', release[0], '-n', release[1]]))
    if acceptance:
        ready_name = {'core-after': 'core-ready', 'local-after': 'local-ready', 'fresh-core': 'fresh-ready'}[args.stage]
        checkpoint = json.loads((args.directory / (ready_name + '.json')).read_text())
        require(checkpoint.get('schema') == 1 and checkpoint.get('stage') == ready_name and checkpoint.get('observerSHA256') == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'unknown or changed ready proof')
        require(checkpoint['daemonsetUID'] == ds['metadata']['uid'] and checkpoint['clusterUID'] == snapshot['clusterUID'], 'ready checkpoint identity changed')
        snapshot['readyAt'] = checkpoint['observedAt']
        snapshot.update(backup=get('backup', args.backup), restore=get('restore', args.restore),
                        pvb=get('podvolumebackups', selector='velero.io/backup-name=' + args.backup),
                        pvr=get('podvolumerestores', selector='velero.io/restore-name=' + args.restore))
    proof = validate(snapshot, args.stage, baseline)
    args.directory.mkdir(parents=True, exist_ok=True)
    # Preserve only bounded sanitized evidence; raw release Secrets never leave memory.
    proof['releaseManifestHashes'] = {key: hashlib.sha256(json.dumps(snapshot[key], sort_keys=True).encode()).hexdigest() for key in ('localManifest', 'coreManifest')}
    if acceptance:
        proof['volumeCopies'] = {key: [{'name': v['metadata']['name'], 'phase': v['status']['phase'], 'namespace': v['spec']['pod']['namespace'], 'volume': v['spec']['volume']} for v in snapshot[key]['items']] for key in ('pvb', 'pvr')}
        proof['backup'] = args.backup
        proof['restore'] = args.restore
    proof['agentSpec'] = {'selector': ds['spec']['selector'], 'owner': list(LOCAL if local else CORE),
                          'resourceVersion': ds['metadata']['resourceVersion'], 'status': ds['status']}
    with (args.directory / (args.stage + '.json')).open('x') as output:
        json.dump(proof, output, indent=2)
        output.write('\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
