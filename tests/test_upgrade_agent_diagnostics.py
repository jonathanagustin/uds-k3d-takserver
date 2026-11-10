# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Failure capture fixtures: no cluster, Docker daemon, or credentials needed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tests/upgrade-agent-metadata.py'


class AgentDiagnosticsTests(unittest.TestCase):
    def helper(self, mode, value):
        return subprocess.check_output(['python3', str(HELPER), mode],
                                       input=json.dumps(value), text=True)

    def test_lifecycle_and_invocation_allowlist(self):
        pod = {'spec': {'nodeName': 'k3d-ci-server-0', 'containers': [
            {'name': 'server', 'image': 'agent:v0.88.0',
             'command': ['/zarf'], 'args': ['internal', 'agent']}]},
            'status': {'containerStatuses': [{'name': 'server', 'restartCount': 8,
                'containerID': 'containerd://' + 'a' * 64,
                'lastState': {'terminated': {'exitCode': 2, 'reason': 'Error',
                    'startedAt': '2026-11-01T00:00:00Z', 'finishedAt': '2026-11-01T00:00:01Z',
                    'message': 'opaque-credential'}}}]}}
        output = self.helper('pod', pod)
        self.assertIn('"exitCode": 2', output)
        self.assertIn('finishedAt', output)
        self.assertIn('"restartCount": 8', output)
        self.assertIn('"command": ["/zarf"]', output)
        self.assertNotIn('opaque-credential', output)
        pod['spec']['containers'][0]['args'] += ['--token', 'opaque-argument']
        output = self.helper('pod', pod)
        self.assertIn('omitted unfamiliar invocation', output)
        self.assertNotIn('opaque-argument', output)

    def test_cri_selects_only_agent_current_and_predecessor(self):
        containers = []
        for number, namespace, name in [(1, 'zarf', 'agent-hook-abc'),
                                        (2, 'zarf', 'agent-hook-abc'),
                                        (3, 'zarf', 'agent-hook-abc'),
                                        (4, 'other', 'agent-hook-abc'),
                                        (5, 'zarf', 'unrelated')]:
            containers.append({'id': str(number) * 64, 'createdAt': number,
                               'labels': {'io.kubernetes.pod.namespace': namespace,
                                          'io.kubernetes.pod.name': name,
                                          'io.kubernetes.container.name': 'server'}})
        self.assertEqual([line.split()[0] for line in self.helper('cri', {'containers': containers}).splitlines()],
                         ['3' * 64, '2' * 64])

    def test_docker_fallback_when_api_is_unavailable_and_auth_is_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'uds').write_text('#!/bin/sh\nexit 1\n')
            docker = directory / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[0] == 'ps':
    print('k3d-ci-server-0')
    print('k3d-ci-serverlb')
elif 'ps' in args:
    print(json.dumps({'containers': [{'id': 'a'*64, 'createdAt': 2, 'labels': {
        'io.kubernetes.pod.namespace': 'zarf', 'io.kubernetes.pod.name': 'agent-hook-abc',
        'io.kubernetes.container.name': 'server'}}, {'id': 'b'*64, 'createdAt': 1, 'labels': {
        'io.kubernetes.pod.namespace': 'zarf', 'io.kubernetes.pod.name': 'agent-hook-abc',
        'io.kubernetes.container.name': 'server'}}]}))
elif args[-1].startswith('a'):
    print('panic: actual-agent-crash')
    print('password=unique-password')
else:
    print('registryAuth: opaque-registry-value')
    print('unrelated-fragment-must-also-disappear')
''')
            for path in (docker, directory / 'uds'):
                path.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'tests/upgrade-agent-diagnostics.sh'), 'fixture'],
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True, check=True, timeout=35)
            output = result.stdout + result.stderr
            self.assertIn('actual-agent-crash', output)
            self.assertIn('Node CRI agent log', output)
            self.assertNotIn('unique-password', output)
            self.assertNotIn('opaque-registry-value', output)
            self.assertNotIn('unrelated-fragment', output)
            self.assertIn('Agent Service selector unavailable', output)


if __name__ == '__main__':
    unittest.main()
