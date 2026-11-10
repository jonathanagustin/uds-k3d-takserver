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

    def capture_fixture(self, docker_body, uds_body=None):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for name, body in {'uds': ('#!/usr/bin/env python3\n' + uds_body) if uds_body is not None else '#!/bin/sh\nexit 1\n',
                               'docker': '#!/usr/bin/env python3\n' + docker_body}.items():
                path = directory / name
                path.write_text(body)
                path.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'tests/upgrade-agent-diagnostics.sh'), 'fixture'],
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True, check=True, timeout=35)
            return result.stdout + result.stderr

    @staticmethod
    def physical_pod():
        return {'metadata': {'namespace': 'zarf', 'name': 'agent-hook-fixture',
                             'uid': '12345678-1234-1234-1234-123456789abc'},
                'spec': {'nodeName': 'k3d-fixture-server-0', 'containers': [{'name': 'server'}]},
                'status': {'containerStatuses': [{'name': 'server', 'restartCount': 2,
                                                  'containerID': 'containerd://' + 'a' * 64}]}}

    @staticmethod
    def physical_api(pod):
        return f"""import json, sys
pod = {pod!r}
if 'service' in sys.argv:
    print(json.dumps({{'spec': {{'selector': {{'app': 'agent-hook'}}}}}}))
elif 'pods' in sys.argv and any(arg.startswith('jsonpath=') for arg in sys.argv):
    print('agent-hook-fixture')
elif 'pod' in sys.argv:
    print(json.dumps(pod))
"""

    def test_no_crictl_uses_only_api_uid_and_bounded_current_previous_attempts(self):
        body = """import sys
if sys.argv[1] == 'ps':
    print('k3d-fixture-server-0')
elif 'crictl' in sys.argv:
    print("No help topic for 'crictl'")
    sys.exit(3)
elif 'sh' in sys.argv:
    assert sys.argv[-1].startswith('/var/log/pods/zarf_agent-hook-fixture_12345678-1234-1234-1234-123456789abc/server/')
    assert sys.argv[-1].split('/')[-1] in ('2.log', '1.log', '0.log')
    assert '-L' in sys.argv[-4]
    if sys.argv[-1].endswith('/1.log'): print('previous-attempt-one')
    if sys.argv[-1].endswith('/0.log'): print('older-attempt-zero')
"""
        output = self.capture_fixture(body, self.physical_api(self.physical_pod()))
        self.assertIn("No help topic for 'crictl'", output)
        self.assertIn('Node CRI container list (k3d-fixture-server-0): exit=3', output)
        self.assertEqual(output.count('Node physical agent attempt:'), 3)
        self.assertIn('successful empty stream bytes=0', output)
        self.assertIn('previous-attempt-one', output)
        self.assertIn('older-attempt-zero', output)
        self.assertIn('exit=0 captured_bytes=0', output)
        self.assertLess(output.index('attempt=2'), output.index('attempt=1'))
        self.assertLess(output.index('attempt=1'), output.index('attempt=0'))

    def test_physical_identity_rejects_paths_missing_ids_and_unbounded_attempts(self):
        valid = self.physical_pod()
        lines = self.helper('physical', valid).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual([line.split('\t')[-1] for line in lines], ['2', '1', '0'])
        import copy
        for section, key, value in [('metadata', 'namespace', 'other'),
                                     ('metadata', 'name', 'agent-hook-../../private'),
                                     ('metadata', 'uid', '../../private'),
                                     ('spec', 'nodeName', 'host')]:
            pod = copy.deepcopy(valid)
            pod[section][key] = value
            result = subprocess.run(['python3', str(HELPER), 'physical'], input=json.dumps(pod),
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        for attempt in (-1, True, 2147483648, '2'):
            pod = copy.deepcopy(valid)
            pod['status']['containerStatuses'][0]['restartCount'] = attempt
            result = subprocess.run(['python3', str(HELPER), 'physical'], input=json.dumps(pod),
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        valid['status']['containerStatuses'][0]['restartCount'] = 2147483647
        self.assertEqual(len(self.helper('physical', valid).splitlines()), 3)

    def test_physical_fallback_omits_oversize_auth_and_incomplete_reads(self):
        prefix = """import sys
if sys.argv[1] == 'ps': print('k3d-fixture-server-0')
elif 'crictl' in sys.argv:
    print("No help topic for 'crictl'"); sys.exit(3)
elif 'sh' in sys.argv:
 """
        cases = [("print('x' * 65537)", 'omitted oversized stream', 'x' * 100),
                 ("print('{\"auths\":{\"registry\":{\"auth\":\"never-print-auth\"}}}')",
                  'Omitted authentication-bearing', 'never-print-auth'),
                 ("print('never-print-incomplete'); print('physical read failed', file=sys.stderr); sys.exit(7)",
                  'exit=7 captured_bytes=', 'never-print-incomplete')]
        for action, expected, forbidden in cases:
            with self.subTest(expected=expected):
                output = self.capture_fixture(prefix + action + '\n', self.physical_api(self.physical_pod()))
                self.assertIn(expected, output)
                self.assertNotIn(forbidden, output)

    def test_actual_physical_reader_refuses_symlinks_without_host_access(self):
        for mode in ('regular', 'file-link', 'pod-link', 'prefix-link'):
            body = f"""import pathlib, subprocess, sys
mode = {mode!r}
if sys.argv[1] == 'ps': print('k3d-fixture-server-0')
elif 'crictl' in sys.argv: sys.exit(3)
elif 'sh' in sys.argv:
    base = pathlib.Path(__file__).parent / 'fake-node'
    base.mkdir(exist_ok=True)
    secret = base / 'private-file'
    secret.write_text('should-never-read-this')
    var = base / 'var'
    var.mkdir(exist_ok=True)
    log = base / 'private-log' if mode == 'prefix-link' else var / 'log'
    log.mkdir(exist_ok=True)
    if mode == 'prefix-link' and not (var / 'log').exists():
        (var / 'log').symlink_to(log, target_is_directory=True)
    pods = log / 'pods'
    pods.mkdir(exist_ok=True)
    directory = sys.argv[-2]
    pod = base / 'private-pod' if mode == 'pod-link' else pods / directory
    pod.mkdir(exist_ok=True)
    if mode == 'pod-link' and not (pods / directory).exists():
        (pods / directory).symlink_to(pod, target_is_directory=True)
    server = pod / 'server'
    server.mkdir(exist_ok=True)
    for number in range(3):
        file = server / (str(number) + '.log')
        if not file.exists():
            if mode == 'file-link': file.symlink_to(secret)
            else: file.write_text('actual-owned-log' if mode == 'regular' else 'should-never-read-this')
    script = sys.argv[-4].replace('/var', str(var))
    file = sys.argv[-1].replace('/var', str(var))
    result = subprocess.run(['sh', '-c', script, 'sh', directory, file], capture_output=True)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)
"""
            with self.subTest(mode=mode):
                output = self.capture_fixture(body, self.physical_api(self.physical_pod()))
                self.assertNotIn('should-never-read-this', output)
                if mode == 'regular':
                    self.assertIn('actual-owned-log', output)
                else:
                    self.assertIn('exit=66 captured_bytes=0', output)
                    self.assertNotIn('actual-owned-log', output)

    def test_physical_fallback_requires_live_api_and_discovered_node(self):
        body = """import sys
if sys.argv[1] == 'ps': print('k3d-fixture-server-0')
elif 'crictl' in sys.argv: sys.exit(3)
elif 'sh' in sys.argv: print('unexpected-physical-read')
"""
        output = self.capture_fixture(body)
        self.assertNotIn('unexpected-physical-read', output)
        pod = self.physical_pod()
        pod['spec']['nodeName'] = 'k3d-other-server-0'
        output = self.capture_fixture(body, self.physical_api(pod))
        self.assertIn('omitted undiscovered node', output)
        self.assertNotIn('unexpected-physical-read', output)

    def test_discovery_failure_and_successful_zero_nodes_are_distinct(self):
        output = self.capture_fixture("import sys\nprint('Authorization: Bearer unique-marker')\nsys.exit(7)\n")
        self.assertIn('Docker node discovery: exit=7', output)
        self.assertIn('Omitted authentication-bearing', output)
        self.assertNotIn('unique-marker', output)
        self.assertIn('eligible=0', output)
        output = self.capture_fixture("pass\n")
        self.assertIn('Docker node discovery: exit=0', output)
        self.assertIn('eligible=0', output)

    def test_cri_failure_invalid_json_and_zero_matches_are_observable(self):
        prefix = "import sys\nif sys.argv[1] == 'ps':\n print('k3d-fixture-server-0')\nelse:\n "
        for body, expected in (
                ("print('registryAuth: never-print-this'); sys.exit(9)", 'exit=9'),
                ("print('not-json')", 'invalid or unavailable JSON/schema'),
                ("print('{\"containers\": []}')", '\"agent_matches\": 0')):
            with self.subTest(body=body):
                output = self.capture_fixture(prefix + body + '\n')
                self.assertIn(expected, output)
                self.assertNotIn('never-print-this', output)

    def test_empty_cri_logs_are_distinct_from_successful_content(self):
        body = """import json, sys
if sys.argv[1] == 'ps':
    print('k3d-fixture-server-0')
elif 'ps' in sys.argv:
    print(json.dumps({'containers': [{'id': 'a'*64, 'createdAt': 1, 'labels': {
        'io.kubernetes.pod.namespace': 'zarf', 'io.kubernetes.pod.name': 'agent-hook-abc',
        'io.kubernetes.container.name': 'server'}}]}))
"""
        output = self.capture_fixture(body)
        self.assertIn('Node CRI log retrieval: exit=0', output)
        self.assertIn('successful empty stream', output)
        self.assertIn('"agent_matches": 1', output)

    def test_newest_cri_evidence_survives_complete_bounded_output(self):
        body = """import json, sys
if sys.argv[1] == 'ps':
    print('k3d-fixture-server-0')
    print('k3d-fixture-agent-0')
elif 'ps' in sys.argv:
    print(json.dumps({'containers': [{'id': str(i)*64, 'createdAt': i, 'labels': {
        'io.kubernetes.pod.namespace': 'zarf', 'io.kubernetes.pod.name': 'agent-hook-abc',
        'io.kubernetes.container.name': 'server'}} for i in (1, 2)]}))
else:
    print('newest-first-evidence' if sys.argv[-1].startswith('2') else 'older-evidence')
    for i in range(79):
        print('bounded fixture log line', i)
"""
        output = self.capture_fixture(body)
        self.assertGreater(len(output.splitlines()), 300)
        self.assertIn('Docker node discovery: exit=0', output)
        self.assertEqual(output.count('newest-first-evidence'), 2)
        self.assertEqual(output.count('older-evidence'), 2)
        self.assertIn('Agent Service selector unavailable', output)

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

    def test_live_probe_timings_and_standard_resources_are_reported(self):
        healthz = {'httpGet': {'path': '/healthz', 'scheme': 'HTTPS', 'port': 8443},
                   'periodSeconds': 10, 'timeoutSeconds': 1, 'failureThreshold': 3}
        container = {'name': 'server', 'livenessProbe': healthz,
                     'readinessProbe': {**healthz, 'periodSeconds': 3, 'timeoutSeconds': 2,
                                        'failureThreshold': 2},
                     'resources': {'requests': {'cpu': '100m', 'memory': '32Mi'},
                                   'limits': {'cpu': '500m', 'memory': '128Mi'}}}
        rows = [json.loads(line) for line in self.helper('pod', {
            'spec': {'containers': [container]}}).splitlines()]
        resources = next(row['resources'] for row in rows if 'resources' in row)
        probes = next(row for row in rows if 'startupProbe' in row)
        self.assertEqual(resources, container['resources'])
        self.assertEqual(probes['startupProbe'], {'configured': False})
        self.assertEqual(probes['livenessProbe'], {'configured': True, **healthz})
        self.assertEqual(probes['readinessProbe']['timeoutSeconds'], 2)
        container['startupProbe'] = {**healthz, 'initialDelaySeconds': 0,
                                     'failureThreshold': 30, 'terminationGracePeriodSeconds': 5}
        rows = [json.loads(line) for line in self.helper('pod', {
            'spec': {'containers': [container]}}).splitlines()]
        startup = next(row['startupProbe'] for row in rows if 'startupProbe' in row)
        self.assertEqual(startup, {'configured': True, **container['startupProbe']})
        # Missing timings stay missing; source defaults are not live evidence.
        container['livenessProbe'] = {'httpGet': healthz['httpGet']}
        rows = [json.loads(line) for line in self.helper('pod', {
            'spec': {'containers': [container]}}).splitlines()]
        self.assertNotIn('timeoutSeconds', next(row['livenessProbe'] for row in rows
                                               if 'livenessProbe' in row))

    def test_probe_actions_and_custom_resources_cannot_disclose_secrets(self):
        probes = [
            {'exec': {'command': ['sh', '-c', 'opaque-exec-secret']}},
            {'httpGet': {'path': '/healthz?token=opaque-query-secret', 'port': 8443,
                         'scheme': 'HTTPS'}},
            {'httpGet': {'path': '/healthz', 'port': 8443, 'scheme': 'HTTPS',
                         'httpHeaders': [{'name': 'Authorization', 'value': 'opaque-header-secret'}]}},
            {'httpGet': {'path': '/healthz', 'port': 8443, 'scheme': 'HTTPS',
                         'host': 'opaque-host-secret'}},
            {'tcpSocket': {'host': 'opaque-tcp-secret', 'port': 8443}},
            {'grpc': {'service': 'opaque-grpc-secret', 'port': 8443}},
        ]
        for probe in probes:
            with self.subTest(probe=probe):
                container = {'name': 'server', 'startupProbe': {
                    **probe, 'initialDelaySeconds': 4, 'periodSeconds': 'opaque-timing-secret',
                    'timeoutSeconds': True, 'failureThreshold': -1},
                    'resources': {'requests': {'cpu': '100m', 'memory': 'opaque-resource-secret',
                                               'custom.example/opaque-custom-key': 'opaque-custom-value'},
                                  'limits': {'cpu': '500m'}}}
                output = self.helper('pod', {'spec': {'containers': [container]}})
                self.assertNotIn('opaque-', output)
                self.assertNotIn('custom.example', output)
                metadata = next(json.loads(line)['startupProbe'] for line in output.splitlines()
                                if 'startupProbe' in line)
                self.assertEqual(metadata['initialDelaySeconds'], 4)
                self.assertNotIn('timeoutSeconds', metadata)
                self.assertNotIn('failureThreshold', metadata)
                self.assertIn('omitted unfamiliar or custom action', metadata['action'])

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
