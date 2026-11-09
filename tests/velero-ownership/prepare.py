#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare an experimental Core bundle copy; never deploy or edit the input."""
import argparse
import copy
from pathlib import Path
import yaml


def prepare(bundle, exemption):
    result = copy.deepcopy(bundle)
    packages = {p['name']: p for p in result['packages']}
    for name in ('core-base', 'core-backup-restore'):
        if packages[name].get('ref') != '1.16.0-upstream':
            raise ValueError('experiment requires the reviewed Core 1.16.0 packages')
    if exemption.get('kind') != 'Exemption' or exemption['metadata']['name'] != 'velero-node-agent':
        raise ValueError('expected the actual rendered local agent exemption')
    entries = exemption['spec']['exemptions']
    expected_policies = [
        {'DisallowPrivileged', 'RequireNonRootUser', 'DropAllCapabilities', 'RestrictCapabilities', 'RestrictHostPathWrite', 'RestrictVolumeTypes', 'DisallowHostNamespaces', 'RestrictSELinuxType'},
        {'DisallowPrivileged', 'RequireNonRootUser', 'DropAllCapabilities', 'RestrictHostPathWrite', 'RestrictVolumeTypes'}]
    if len(entries) != 2 or any(e['matcher'] != {'namespace': 'velero', 'name': name, 'kind': 'pod'} or set(e['policies']) != policies for e, name, policies in zip(entries, ('^node-agent-.*', '.*'), expected_policies)):
        raise ValueError('unexpected exemption scope')
    values = packages['core-base'].setdefault('overrides', {}).setdefault('uds-exemptions', {}).setdefault('uds-exemptions', {}).setdefault('values', [])
    custom = next((v for v in values if v['path'] == 'exemptions.custom'), None)
    if custom is None:
        custom = {'path': 'exemptions.custom', 'value': []}
        values.append(custom)
    if not isinstance(custom['value'], list):
        raise ValueError('custom exemptions must be a concrete list, not a templated replacement')
    if any(e['name'] == 'velero-node-agent-bootstrap' for e in custom['value']):
        raise ValueError('bootstrap name already exists; inspect it instead of replacing it')
    custom['value'].append({'name': 'velero-node-agent-bootstrap', 'exemptions': copy.deepcopy(entries)})
    upstream = packages['core-backup-restore']['overrides']['velero']['velero']['values']
    desired = {
        'deployNodeAgent': True,
        'nodeAgent': {
            'annotations': {'helm.sh/resource-policy': 'keep'},
            'podSecurityContext': {'runAsUser': 0, 'runAsGroup': 0, 'runAsNonRoot': False},
            'containerSecurityContext': {'privileged': True, 'runAsUser': 0, 'runAsGroup': 0, 'runAsNonRoot': False},
            'resources': {'requests': {'cpu': '25m', 'memory': '128Mi'}, 'limits': {'memory': '512Mi'}},
            'tolerations': [{'operator': 'Exists'}],
            'extraArgs': ['--node-agent-configmap=velero-node-agent-config']},
        'configMaps.node-agent-config': {'data': {'node-agent-config.json': '{"privilegedFsBackup":true,"podLabels":{"app.kubernetes.io/name":"velero","app.kubernetes.io/component":"velero-data-mover"}}'}}}
    for path, value in desired.items():
        if any(v['path'] == path or v['path'].startswith(path + '.') or path.startswith(v['path'] + '.') for v in upstream):
            raise ValueError('existing overlapping agent override must be reviewed, not replaced')
        upstream.append({'path': path, 'value': value})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--exemption', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate = prepare(yaml.safe_load(args.bundle.read_text()), yaml.safe_load(args.exemption.read_text()))
    # Never overwrite an input or a previous candidate with unknown provenance.
    with args.output.open('x') as output:
        yaml.safe_dump(candidate, output, sort_keys=False)


if __name__ == '__main__':
    main()
