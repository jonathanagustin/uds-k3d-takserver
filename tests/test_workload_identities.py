# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Render actual staged identities, retaining shared defaults and scoped rules."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APPS = {'takserver-api', 'takserver-config', 'takserver-messaging', 'takserver-plugins'}


def render(phase):
    result = subprocess.run(['helm', 'template', 'config', str(ROOT / 'charts/takserver'),
                             '--namespace', 'takserver', '--set', f'workloadIdentityPhase={phase}'],
                            text=True, capture_output=True)
    return result, list(yaml.safe_load_all(result.stdout))


class WorkloadIdentities(unittest.TestCase):
    def test_stages_preserve_rules_and_remove_legacy_only_in_strict(self):
        rendered = {}
        for phase in ['shared', 'transition', 'strict', 'rollback']:
            result, docs = render(phase)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = next(doc for doc in docs if doc and doc['kind'] == 'Package')
            self.assertEqual(package['apiVersion'], 'uds.dev/v1alpha1')
            rules = package['spec']['network']['allow']
            rendered[phase] = rules
            accounts = {doc['metadata']['name'] for doc in docs if doc and doc['kind'] == 'ServiceAccount'}
            self.assertEqual(accounts & APPS, set() if phase == 'shared' else APPS)
            if phase != 'shared':
                bindings = [doc for doc in docs if doc and doc['kind'] == 'RoleBinding'
                            and doc['metadata']['name'] in {app + '-discovery' for app in APPS}]
                self.assertEqual(len(bindings), 4)
                self.assertTrue(all(binding['roleRef']['kind'] == 'Role' for binding in bindings))
                self.assertTrue(all(binding['roleRef']['name'] == 'takserver-workload-discovery' for binding in bindings))
                discovery = next(doc for doc in docs if doc and doc['kind'] == 'Role'
                                 and doc['metadata']['name'] == 'takserver-workload-discovery')
                self.assertFalse(any('pods/log' in rule['resources'] for rule in discovery['rules']))
                log_binding = next(doc for doc in docs if doc and doc['kind'] == 'RoleBinding'
                                   and doc['metadata']['name'] == 'takserver-config-ignite-log')
                self.assertEqual([subject['name'] for subject in log_binding['subjects']], ['takserver-config'])
        for rule in rendered['strict']:
            if rule.get('remoteServiceAccount') not in APPS:
                self.assertIn(rule, rendered['shared'])
                continue
            legacy = dict(rule, remoteServiceAccount='takserver-ignite')
            self.assertIn(legacy, rendered['shared'])
            self.assertIn(rule, rendered['transition'])
            transitional = dict(legacy, description=legacy['description'] + ' (legacy identity during migration)')
            self.assertIn(transitional, rendered['transition'])
            self.assertIn(transitional, rendered['rollback'])
            self.assertNotIn(transitional, rendered['strict'])
        self.assertTrue(any(rule.get('remoteServiceAccount') in APPS for rule in rendered['strict']))
        for rule in rendered['strict']:
            source = rule.get('remoteSelector', {}).get('app')
            if rule.get('direction') == 'Ingress' and source in APPS:
                self.assertEqual(rule.get('remoteServiceAccount'), source)
                self.assertNotEqual(rule.get('remoteServiceAccount'), 'negative-control')


    def test_invalid_phase_fails_closed(self):
        result, _ = render('unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be shared, transition, strict or rollback', result.stderr)
