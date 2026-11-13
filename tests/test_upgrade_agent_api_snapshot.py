# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Same-agent namespace snapshot selection, failure privacy and command contract."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tests/agent-api-snapshot.py'
SPEC = importlib.util.spec_from_file_location('agent_api_snapshot', HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
UID = '12345678-1234-1234-1234-123456789abc'


class AgentApiSnapshotTests(unittest.TestCase):
    def pod(self):
        return {'metadata': {'namespace': 'zarf', 'name': 'agent-hook-fixture', 'uid': UID},
                'spec': {'nodeName': 'k3d-fixture-server-0', 'serviceAccountName': 'agent-hook', 'containers': [{'name': 'server'}]}}

    def test_rejects_untrusted_exec_selection(self):
        for section, key, value in [('metadata', 'namespace', 'other'),
                                     ('metadata', 'name', 'agent-hook-../private'),
                                     ('metadata', 'uid', 'not-an-id'),
                                     ('spec', 'serviceAccountName', 'account\nsecret'),
                                     ('spec', 'nodeName', '../private')]:
            pod = copy.deepcopy(self.pod())
            pod[section][key] = value
            with self.subTest(key=key), self.assertRaises((AssertionError, TypeError)):
                MODULE.identity(pod)
        pod = self.pod()
        pod['spec']['containers'] *= 2
        with self.assertRaises(AssertionError):
            MODULE.identity(pod)

    def invoke(self, body, count=1):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            executable = directory / 'uds'
            executable.write_text('#!/usr/bin/env python3\n' + body)
            executable.chmod(0o755)
            pod = directory / 'pod.json'
            pod.write_text(json.dumps(self.pod()))
            result = subprocess.run(['python3', str(HELPER), *([str(pod)] * count)],
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True, check=True, timeout=10)
            self.assertEqual(result.stderr, '')
            return result.stdout

    def test_same_container_fixed_read_only_command_and_two_pod_cap(self):
        output = self.invoke(f"""import sys
assert sys.argv[1:] == ['zarf', 'tools', 'kubectl', '--request-timeout=2s',
    'exec', '-n', 'zarf', 'agent-hook-fixture', '-c', 'server', '--', '/zarf',
    'tools', 'kubectl', '--request-timeout=2s', 'get', 'namespace', 'velero',
    '-o', 'jsonpath={{.metadata.uid}}']
print('{UID}', end='')
""", count=3)
        records = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record['result'], 'lookup-succeeded')
            self.assertEqual(record['agent']['uid'], UID)
            self.assertEqual(record['targetUID'], UID)
            self.assertEqual(record['snapshot'], 'postfailure')
            self.assertIsInstance(record['elapsed_ms'], int)

    def test_failure_and_oversize_outputs_never_escape(self):
        for code, stdout, expected in [(7, 'Bearer never-print', 'exec-or-lookup-failed'),
                                       (127, '', 'exec-unavailable'),
                                       (124, '', 'exec-or-lookup-timeout'),
                                       (0, 'x' * 500, 'invalid-lookup-output'),
                                       (0, UID + '\nBearer never-print', 'invalid-lookup-output')]:
            body = f"import sys\nprint({stdout!r}, end='')\nprint('password=never-print', file=sys.stderr)\nsys.exit({code})\n"
            with self.subTest(code=code, expected=expected):
                output = self.invoke(body)
                self.assertNotIn('never-print', output)
                self.assertNotIn('x' * 50, output)
                self.assertEqual(json.loads(output)['result'], expected)

    def test_real_outer_timeout_is_bounded_and_private(self):
        output = self.invoke("import time\ntime.sleep(20)\n")
        record = json.loads(output)
        self.assertEqual(record['result'], 'exec-or-lookup-timeout')
        self.assertLess(record['elapsed_ms'], 5000)

    def test_failure_pipeline_retains_primary_logs_before_snapshot(self):
        from tests.test_upgrade_agent_diagnostics import AgentDiagnosticsTests
        fixture = AgentDiagnosticsTests()
        pod = self.pod()
        # API metadata is selected once; nested exec uses no exported credential.
        body = f"""import json, sys
pod = {pod!r}
if 'exec' in sys.argv:
    print('{UID}', end='')
elif 'service' in sys.argv:
    print(json.dumps({{'spec': {{'selector': {{'app': 'agent-hook'}}}}}}))
elif 'pods' in sys.argv and any(a.startswith('jsonpath=') for a in sys.argv):
    print('agent-hook-fixture')
elif 'pod' in sys.argv:
    print(json.dumps(pod))
elif 'logs' in sys.argv:
    print('retained-primary-log')
"""
        output = fixture.capture_fixture("import sys\nsys.exit(1)\n", body)
        self.assertIn('lookup-succeeded', output)
        self.assertEqual(output.count('retained-primary-log'), 2)
        self.assertLess(output.rindex('retained-primary-log'), output.index('lookup-succeeded'))

    def test_probe_is_after_all_primary_logs_and_keeps_existing_deadlines(self):
        script = (ROOT / 'tests/upgrade-agent-diagnostics.sh').read_text()
        self.assertLess(script.index('safe logs -n zarf "${pod}" -c server --previous'),
                        script.index('agent-api-snapshot.py'))
        self.assertLess(script.index('done <<<"${pods}"'), script.index('agent-api-snapshot.py'))
        self.assertIn('elapsed < 30', script)
        self.assertIn("'3s'", HELPER.read_text())


if __name__ == '__main__':
    unittest.main()
