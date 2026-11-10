#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Allowlisted agent metadata; callers sanitize the entire result before output."""
import json
import re
import sys

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
elif sys.argv[1] == 'cri':
    matches = []
    for container in value.get('containers', []):
        labels = container.get('labels', {})
        if (labels.get('io.kubernetes.pod.namespace') == 'zarf'
                and labels.get('io.kubernetes.container.name') == 'server'
                and 'agent-hook' in labels.get('io.kubernetes.pod.name', '')
                and re.fullmatch('[a-f0-9]{12,64}', container.get('id', ''))):
            matches.append(container)
    # Include exited predecessors, newest first, with a strict per-node cap.
    for container in sorted(matches, key=lambda item: int(item.get('createdAt', 0)), reverse=True)[:2]:
        print(container['id'], json.dumps({
            'createdAt': int(container.get('createdAt', 0)),
            'state': container.get('state') if container.get('state') in
                ('CONTAINER_CREATED', 'CONTAINER_RUNNING', 'CONTAINER_EXITED', 'CONTAINER_UNKNOWN') else None,
            'attempt': int(container.get('metadata', {}).get('attempt', 0))}))
