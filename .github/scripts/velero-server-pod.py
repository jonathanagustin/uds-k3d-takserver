#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Select one live server pod through the Velero Deployment/ReplicaSet UID chain."""
import json
import re
import sys


def select(value):
    items = value['items']
    if not isinstance(items, list) or len(items) > 256:
        raise ValueError('inventory bound')
    items = [obj for obj in items if obj['metadata'].get('namespace') == 'velero']
    deployments = [obj for obj in items if obj['kind'] == 'Deployment' and obj['metadata']['name'] == 'velero']
    if len(deployments) != 1 or deployments[0]['metadata'].get('deletionTimestamp'):
        raise ValueError('server deployment unavailable')
    uid = deployments[0]['metadata']['uid']
    if not isinstance(uid, str) or not uid:
        raise ValueError('server deployment identity')

    def owned(obj, kind, identities):
        owners = [owner for owner in obj['metadata'].get('ownerReferences', []) if owner.get('controller') is True]
        return len(owners) == 1 and owners[0].get('apiVersion') == 'apps/v1' and owners[0].get('kind') == kind and owners[0].get('uid') in identities

    replicas = {obj['metadata']['uid'] for obj in items if obj['kind'] == 'ReplicaSet' and
                not obj['metadata'].get('deletionTimestamp') and owned(obj, 'Deployment', {uid})}
    pods = [obj for obj in items if obj['kind'] == 'Pod' and not obj['metadata'].get('deletionTimestamp') and
            obj.get('status', {}).get('phase') == 'Running' and owned(obj, 'ReplicaSet', replicas) and
            sum(container.get('name') == 'velero' for container in obj.get('spec', {}).get('containers', [])) == 1]
    if len(pods) != 1:
        raise ValueError('server pod ambiguous or unavailable')
    name = pods[0]['metadata']['name']
    if not isinstance(name, str) or not re.fullmatch('[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', name):
        raise ValueError('server pod name')
    return name


def main():
    try:
        data = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError('input bound')
        name = select(json.loads(data))
    except (ValueError, TypeError, KeyError):
        print('Velero server pod selection unavailable', file=sys.stderr)
        return 2
    print(name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
