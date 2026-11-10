#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Allowlisted agent metadata; callers sanitize the entire result before output."""
import json
import re
import sys


def probe_metadata(probe):
    if not isinstance(probe, dict):
        return {'configured': False}
    result = {'configured': True}
    for key in ('initialDelaySeconds', 'periodSeconds', 'timeoutSeconds',
                'successThreshold', 'failureThreshold', 'terminationGracePeriodSeconds'):
        value = probe.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    action = probe.get('httpGet', {})
    if (isinstance(action, dict) and action.get('path') == '/healthz'
            and action.get('scheme') in ('HTTP', 'HTTPS')
            and type(action.get('port')) is int and action['port'] == 8443
            and not action.get('host') and not action.get('httpHeaders')
            and not any(key in probe for key in ('exec', 'tcpSocket', 'grpc'))):
        result['httpGet'] = {'path': '/healthz', 'scheme': action['scheme'], 'port': 8443}
    else:
        result['action'] = '[omitted unfamiliar or custom action]'
    return result


def resource_metadata(resources):
    result = {}
    if not isinstance(resources, dict):
        return result
    # Quantities contain only numeric syntax and Kubernetes unit suffixes.
    # Never print custom resource keys or arbitrary string values.
    quantity = r'[0-9]+(?:\.[0-9]+)?(?:[EPTGMK]i|[EPTGMkKmun]|[eE][+-]?[0-9]+)?'
    for kind in ('requests', 'limits'):
        values = resources.get(kind, {})
        if not isinstance(values, dict):
            continue
        result[kind] = {key: values[key] for key in ('cpu', 'memory')
                        if isinstance(values.get(key), str) and re.fullmatch(quantity, values[key])}
    return result


value = json.load(sys.stdin)
if sys.argv[1] == 'pod':
    spec = value.get('spec', {})
    print(json.dumps({'node': spec.get('nodeName'), 'uid': value.get('metadata', {}).get('uid')}))
    for container in spec.get('containers', []):
        if container.get('name') == 'server':
            # Positional arguments can be credentials. Only the official agent
            # invocation is public; omit unfamiliar command/args wholesale.
            command = container.get('command', [])
            args = container.get('args', [])
            allowed = all(item in ('/zarf', 'zarf', 'internal', 'agent', '--log-level=debug',
                                             '--log-format=console', '--no-color')
                          for item in command + args)
            print(json.dumps({'image': container.get('image'),
                              'command': command if allowed else '[omitted unfamiliar invocation]',
                              'args': args if allowed else '[omitted unfamiliar invocation]'}))
            print(json.dumps({'resources': resource_metadata(container.get('resources'))}))
            print(json.dumps({key: probe_metadata(container.get(key)) for key in
                              ('startupProbe', 'livenessProbe', 'readinessProbe')}))
    for status in value.get('status', {}).get('containerStatuses', []):
        if status.get('name') != 'server':
            continue
        print(json.dumps({key: status.get(key) for key in
                          ('name', 'containerID', 'imageID', 'restartCount', 'ready')}))
        for field in ('state', 'lastState'):
            for kind, state in status.get(field, {}).items():
                # message is freeform and can contain environment/credentials.
                print(json.dumps({field: {kind: {key: state[key] for key in
                    ('containerID', 'exitCode', 'signal', 'reason', 'startedAt', 'finishedAt')
                    if key in state}}}))
elif sys.argv[1] in ('cri', 'cri-summary'):
    assert isinstance(value.get('containers'), list), 'missing CRI containers array'
    matches = []
    for container in value.get('containers', []):
        labels = container.get('labels', {})
        if (labels.get('io.kubernetes.pod.namespace') == 'zarf'
                and labels.get('io.kubernetes.container.name') == 'server'
                and 'agent-hook' in labels.get('io.kubernetes.pod.name', '')
                and re.fullmatch('[a-f0-9]{12,64}', container.get('id', ''))):
            matches.append(container)
    if sys.argv[1] == 'cri-summary':
        containers = value['containers']
        counts = {name: sum(key in container.get('labels', {}) for container in containers)
                  for name, key in (('namespace_labels', 'io.kubernetes.pod.namespace'),
                                    ('container_labels', 'io.kubernetes.container.name'),
                                    ('pod_labels', 'io.kubernetes.pod.name'))}
        print('Node CRI candidate selection:', json.dumps({
            'containers': len(containers), **counts, 'agent_matches': len(matches),
            'selected': min(len(matches), 2)}))
        sys.exit(0)
    # Include exited predecessors, newest first, with a strict per-node cap.
    for container in sorted(matches, key=lambda item: int(item.get('createdAt', 0)), reverse=True)[:2]:
        print(container['id'], json.dumps({
            'createdAt': int(container.get('createdAt', 0)),
            'state': container.get('state') if container.get('state') in
                ('CONTAINER_CREATED', 'CONTAINER_RUNNING', 'CONTAINER_EXITED', 'CONTAINER_UNKNOWN') else None,
            'attempt': int(container.get('metadata', {}).get('attempt', 0))}))
