# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Render actual staged identities, retaining shared defaults and scoped rules."""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
APPS = {'takserver-api', 'takserver-config', 'takserver-messaging', 'takserver-plugins'}
FLOW_SPEC = importlib.util.spec_from_file_location('flow_identity_checks', ROOT / 'tests/flows.py')
flows = importlib.util.module_from_spec(FLOW_SPEC)
FLOW_SPEC.loader.exec_module(flows)


class FlowIdentityChecks(unittest.TestCase):
    """Exercise the actual --check path, without a cluster or observed sockets."""

    @staticmethod
    def policy(spec):
        return {'metadata': {'name': 'generated-test-policy'}, 'spec': spec}

    def findings(self, spec, rules=()):
        response = subprocess.CompletedProcess([], 0, json.dumps({'items': [self.policy(spec)]}))
        with patch.object(flows, 'kubectl', return_value=response):
            return flows.unscoped_policies(rules)

    def check_status(self, rules, policies):
        def kubectl(*args, **kwargs):
            if args[1] in ('pods', 'svc'):
                data = {'items': []}
            elif args[1] == 'package':
                data = {'spec': {'network': {'allow': rules}}}
            elif args[1] == 'authorizationpolicies.security.istio.io':
                self.assertIn('uds/package=' + flows.PACKAGE, args)
                data = {'items': policies}
            else:
                self.fail('unexpected Kubernetes operation: ' + repr(args))
            return subprocess.CompletedProcess(args, 0, json.dumps(data))
        with patch.object(flows, 'kubectl', side_effect=kubectl), \
                patch.object(flows.sys, 'argv', ['flows.py', '--check']), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                flows.main()
            except SystemExit as error:
                return error.code
        return 0

    def test_empty_remote_selector_requires_service_account(self):
        rule = {'direction': 'Ingress', 'remoteSelector': {}, 'port': 47100}
        self.assertEqual(len(flows.unscoped_rules([rule])), 1)
        self.assertEqual(self.check_status([rule], []), 1)
        scoped = dict(rule, remoteServiceAccount='takserver-api')
        self.assertEqual(flows.unscoped_rules([scoped]), [])
        self.assertEqual(self.check_status([scoped], []), 0)

    def test_external_generated_and_egress_rules_keep_their_scope(self):
        for extra in [{'remoteHost': 'example.com'}, {'remoteCidr': '192.0.2.0/24'},
                      {'remoteGenerated': 'KubeAPI'}, {'direction': 'Egress'}]:
            with self.subTest(extra=extra):
                rule = dict({'direction': 'Ingress', 'remoteSelector': {}}, **extra)
                self.assertEqual(flows.unscoped_rules([rule]), [])

    def test_source_free_allow_rules_fail_check_without_observed_flows(self):
        for rule in [{}, {'to': [{'operation': {'ports': ['47100']}}]},
                     {'from': []}, {'from': [{}]}, {'from': [{'source': {}}]},
                     {'from': [{'source': {'principals': []}}]}]:
            with self.subTest(rule=rule):
                spec = {'rules': [rule]}
                self.assertEqual(len(self.findings(spec)), 1)
                self.assertEqual(self.check_status([], [self.policy(spec)]), 1)

    def test_empty_allow_none_and_non_allow_policies_are_not_broad_grants(self):
        for spec in [{}, {'rules': []}, {'action': 'ALLOW', 'rules': []},
                     {'action': 'DENY', 'rules': [{}]}, {'action': 'AUDIT', 'rules': [{}]}]:
            with self.subTest(spec=spec):
                self.assertEqual(self.findings(spec), [])
                self.assertEqual(self.check_status([], [self.policy(spec)]), 0)

    def test_ip_only_sources_remain_external_but_peer_namespaces_need_identity(self):
        for field in ['ipBlocks', 'remoteIpBlocks']:
            with self.subTest(field=field):
                source = {field: ['192.0.2.0/24']}
                self.assertEqual(self.findings({'rules': [{'from': [{'source': source}]}]}), [])
                source['namespaces'] = [flows.NS]
                self.assertEqual(len(self.findings({'rules': [{'from': [{'source': source}]}]})), 1)

    def test_namespace_patterns_and_exclusions_follow_the_actual_peer_set(self):
        rules = [{'remoteNamespace': 'cloudtak'}]
        for pattern in [flows.NS, 'cloudtak', '*', 'cloud*', '*tak']:
            with self.subTest(pattern=pattern):
                spec = {'rules': [{'from': [{'source': {'namespaces': [pattern]}}]}]}
                self.assertEqual(len(self.findings(spec, rules)), 1)
        for source in [{'namespaces': ['unrelated']}, {'notNamespaces': ['*']},
                       {'notNamespaces': [flows.NS, 'cloudtak']}]:
            with self.subTest(source=source):
                self.assertEqual(self.findings({'rules': [{'from': [{'source': source}]}]}, rules), [])
        self.assertEqual(len(self.findings({'rules': [{'from': [{'source': {'notNamespaces': ['unrelated']}}]}]})), 1)

    def test_scoped_source_does_not_hide_an_all_source_alternative(self):
        scoped = {'source': {'principals': ['cluster.local/ns/takserver/sa/takserver-api']}}
        self.assertEqual(self.findings({'rules': [{'from': [scoped]}]}), [])
        self.assertEqual(len(self.findings({'rules': [{'from': [scoped, {}]}]})), 1)


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
