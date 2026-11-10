# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Native admission barrier contracts; no cluster or images required."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AgentGateTests(unittest.TestCase):
    def test_native_waits_have_bounded_ready_endpoint_conditions(self):
        result = subprocess.check_output([
            'uds', 'zarf', 'tools', 'yq', '-o=json', '.',
            str(ROOT / 'tests/upgrade-agent-gate/zarf.yaml')], text=True)
        package = json.loads(result)
        actions = package['components'][0]['actions']['onDeploy']['before']
        self.assertEqual([a['maxTotalSeconds'] for a in actions], [300, 45, 15])
        self.assertEqual([a['wait']['cluster']['condition'] for a in actions], [
            'Available', '{.subsets[0].addresses[0].targetRef.kind}=Pod',
            '{.subsets[0].ports[0].port}=8443'])
        self.assertTrue(all(a['wait']['cluster']['namespace'] == 'zarf' for a in actions))
        self.assertNotIn('images', package['components'][0])
        component = package['components'][0]
        self.assertEqual(component['files'], [{'source': 'live-health.py',
                                              'target': '.cache/upgrade-agent-gate/live-health.py'}])
        self.assertEqual(component['actions']['onDeploy']['after'], [{
            'description': 'Probe live agent HTTPS health through the Kubernetes API',
            'maxTotalSeconds': 40, 'cmd': 'python3 .cache/upgrade-agent-gate/live-health.py'}])
        self.assertNotIn('serves', actions[-1]['description'])
        subprocess.run(['uds', 'zarf', 'dev', 'lint',
                        str(ROOT / 'tests/upgrade-agent-gate')], check=True)

    def test_insertion_preserves_original_packages_and_values(self):
        script = (ROOT / 'tests/upgrade.sh').read_text()
        start = script.index("uds zarf tools yq -e '\n  .packages[0]")
        end = script.index('uds create "${work}/bundle"', start)
        snippet = script[start:end]
        original = {'kind': 'UDSBundle', 'metadata': {'name': 'fixture', 'version': '1'},
                    'packages': [
                        {'name': 'core-base', 'ref': '1.16.0-upstream',
                         'keylessVerification': {'certificateIdentityRegexp': 'signed'},
                         'exports': [{'name': 'TOKEN'}]},
                        {'name': 'takserver', 'ref': '0.10.0',
                         'imports': [{'name': 'TOKEN', 'package': 'core-base'}],
                         'overrides': {'chart': {'values': [{'path': 'x', 'value': 7}]}}}]}
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'bundle'
            bundle.mkdir()
            path = bundle / 'uds-bundle.yaml'
            path.write_text(json.dumps(original))
            subprocess.run(['bash', '-ec', snippet], env={
                **os.environ, 'work': directory}, check=True)
            updated = json.loads(subprocess.check_output([
                'uds', 'zarf', 'tools', 'yq', '-o=json', '.', str(path)]))
            self.assertEqual(updated['packages'][1]['name'], 'upgrade-agent-gate')
            del updated['packages'][1]
            self.assertEqual(updated, original)
            original['packages'].reverse()
            path.write_text(json.dumps(original))
            self.assertNotEqual(subprocess.run(['bash', '-ec', snippet], env={
                **os.environ, 'work': directory},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode, 0)

    def test_one_bundle_process_and_pre_core_gate(self):
        script = (ROOT / 'tests/upgrade.sh').read_text()
        self.assertNotIn('--resume', script)
        self.assertEqual(script.count('uds deploy "${bundles[0]}"'), 1)
        self.assertLess(script.index('uds run fit-runner'),
                        script.index('uds zarf package deploy "${work}/zarf-package-upgrade-agent-gate'))
        self.assertLess(script.index('uds zarf package deploy "${work}/zarf-package-upgrade-agent-gate'),
                        script.index('uds deploy "${bundles[0]}"'))
        self.assertEqual(script.count('./tests/upgrade-agent-diagnostics.sh'), 2)

    def test_failure_diagnostics_use_live_selector_and_redact_previous_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'uds'
            fake.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if 'service' in args and 'json' in args:
    print(json.dumps({'spec': {'selector': {'actual-agent': 'restored'}}}))
elif 'pods' in args and any('jsonpath=' in a for a in args):
    print('restored-agent')
elif 'logs' in args:
    if '--previous' in args:
        print('password=other-secret-value')
    else:
        print('Authorization: Bearer unique-secret-value')
        print('{\"AUTHORIZATION\":\"Basic third-secret-value\"}')
else:
    print('healthy diagnostic metadata')
''')
            fake.chmod(0o755)
            calls = Path(directory) / 'calls'
            result = subprocess.run([
                'bash', str(ROOT / 'tests/upgrade-agent-diagnostics.sh'), 'fixture'],
                env={**os.environ, 'PATH': directory + ':' + os.environ['PATH'],
                     'CALLS': str(calls)}, text=True, capture_output=True, check=True)
            for secret in ['unique-secret-value', 'other-secret-value', 'third-secret-value']:
                self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertIn('Omitted authentication-bearing', result.stdout)
            self.assertIn('Previous agent log', result.stdout)
            recorded = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertTrue(any('--previous' in call for call in recorded))
            self.assertTrue(any('actual-agent=restored' in call for call in recorded))
            self.assertTrue(all('--request-timeout=2s' in call for call in recorded))
