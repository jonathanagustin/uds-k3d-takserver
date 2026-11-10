# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only live agent gate contracts; fixtures never contact a cluster."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agent_health', ROOT / 'tests/upgrade-agent-gate/live-health.py')
HEALTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEALTH)


def fixture():
    service = {'metadata': {'namespace': 'zarf', 'name': 'agent-hook'},
               'spec': {'selector': {'actual-agent': 'restored'}, 'ports': [{'port': 443, 'targetPort': 8443}]}}
    endpoints = {'metadata': {'namespace': 'zarf', 'name': 'agent-hook'}, 'subsets': [{
        'ports': [{'port': 8443}], 'addresses': [{'ip': '10.42.0.3', 'targetRef': {
            'kind': 'Pod', 'namespace': 'zarf', 'name': 'agent-hook-a', 'uid': 'original-uid'}}]}]}
    pod = {'metadata': {'namespace': 'zarf', 'name': 'agent-hook-a', 'uid': 'original-uid',
                        'labels': {'actual-agent': 'restored'}},
           'status': {'phase': 'Running', 'podIP': '10.42.0.3', 'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    return {'service': service, 'endpoints': endpoints, 'pod': pod}


class AgentHealthTests(unittest.TestCase):
    def request(self, objects, body=b'ok', replace_after=False):
        calls = []
        def get(args, deadline):
            calls.append(args)
            self.assertEqual(args[0], 'get')
            if args[1].startswith('--raw='):
                if replace_after: objects['pod']['metadata']['uid'] = 'replacement'
                return body
            return json.dumps(objects[args[1]]).encode()
        return get, calls

    def two_fixture(self):
        objects = fixture()
        original = objects['pod']
        original['metadata']['ownerReferences'] = [{'kind': 'ReplicaSet', 'uid': 'set-uid', 'controller': True}]
        second = copy.deepcopy(original)
        second['metadata'].update(name='agent-hook-b', uid='second-uid')
        second['status']['podIP'] = '10.42.0.4'
        objects['podmap'] = {pod['metadata']['name']: pod for pod in (original, second)}
        objects['pods'] = {'items': [original, second]}
        objects['deployment'] = {'metadata': {'namespace': 'zarf', 'name': 'agent-hook', 'uid': 'deployment-uid', 'generation': 3},
                                 'spec': {'replicas': 2}, 'status': {'replicas': 2, 'updatedReplicas': 2,
                                 'readyReplicas': 2, 'availableReplicas': 2, 'observedGeneration': 3}}
        objects['replicasets'] = {'items': [{'metadata': {'namespace': 'zarf', 'uid': 'set-uid',
                                    'ownerReferences': [{'kind': 'Deployment', 'uid': 'deployment-uid', 'controller': True}]}}]}
        objects['endpoints']['subsets'][0]['addresses'].append({'ip': '10.42.0.4', 'targetRef': {
            'kind': 'Pod', 'namespace': 'zarf', 'name': 'agent-hook-b', 'uid': 'second-uid'}})
        return objects

    def strict_request(self, objects, response=None):
        calls = []
        def get(args, deadline):
            calls.append(args)
            if args[1].startswith('--raw='):
                return response(args) if response else b'ok'
            if args[1] == 'pod':
                return json.dumps(objects['podmap'][args[2]]).encode()
            return json.dumps(objects[args[1]]).encode()
        return get, calls

    def test_strict_two_requires_both_live_responses_and_owned_current_pods(self):
        objects = self.two_fixture()
        request, calls = self.strict_request(objects)
        self.assertEqual(HEALTH.probe_once(100, request, require_two=True), 2)
        raw = [args[1] for args in calls if args[1].startswith('--raw=')]
        self.assertEqual(len(raw), 2)
        self.assertTrue(any('agent-hook-a:' in value for value in raw))
        self.assertTrue(any('agent-hook-b:' in value for value in raw))
        self.assertTrue(any(args[1] == 'replicasets' for args in calls))

    def test_strict_two_refuses_partial_old_terminating_or_foreign_replicas(self):
        for case in ('one-desired', 'one-ready', 'missing-endpoint', 'second-unready', 'terminating', 'old-generation', 'foreign-owner'):
            with self.subTest(case=case):
                objects = self.two_fixture()
                if case == 'one-desired': objects['deployment']['spec']['replicas'] = 1
                elif case == 'one-ready': objects['deployment']['status']['readyReplicas'] = 1
                elif case == 'missing-endpoint': objects['endpoints']['subsets'][0]['addresses'].pop()
                elif case == 'second-unready': objects['podmap']['agent-hook-b']['status']['conditions'] = []
                elif case == 'terminating': objects['podmap']['agent-hook-b']['metadata']['deletionTimestamp'] = 'now'
                elif case == 'old-generation': objects['deployment']['status']['observedGeneration'] = 2
                else: objects['replicasets']['items'][0]['metadata']['ownerReferences'][0]['uid'] = 'foreign-deployment'
                request, _ = self.strict_request(objects)
                with self.assertRaises(HEALTH.Unavailable):
                    HEALTH.probe_once(100, request, require_two=True)

    def test_strict_two_refuses_second_live_failure_or_endpoint_drift(self):
        for mode in ('bad-second-response', 'changed-endpoints'):
            objects = self.two_fixture()
            def response(args):
                if 'agent-hook-b:' in args[1]:
                    if mode == 'bad-second-response': return b'not-ok'
                    objects['endpoints']['subsets'][0]['addresses'].pop()
                return b'ok'
            request, _ = self.strict_request(objects, response)
            with self.assertRaises(HEALTH.Unavailable):
                HEALTH.probe_once(100, request, require_two=True)

    def test_explicit_strict_cli_selects_two_replica_contract(self):
        with patch.object(HEALTH, 'probe_once', return_value=2) as probe, patch('sys.stdout'):
            self.assertEqual(HEALTH.main(['--require-two-replicas']), 0)
            self.assertTrue(probe.call_args.kwargs['require_two'])

    def test_live_request_uses_validated_pod_and_fixed_https_path(self):
        get, calls = self.request(fixture())
        self.assertEqual(HEALTH.probe_once(100, get), 1)
        self.assertEqual(calls[3], ['get', '--raw=/api/v1/namespaces/zarf/pods/https:agent-hook-a:8443/proxy/healthz'])
        self.assertEqual(calls[2], calls[4])
        self.assertFalse(any('secret' in ' '.join(c) for c in calls))

    def test_stale_wrong_namespace_selector_ip_or_port_never_reaches_proxy(self):
        for case in ('uid', 'namespace', 'selector', 'ip', 'port', 'service-port', 'not-ready', 'path', 'terminating'):
            with self.subTest(case=case):
                objects = fixture(); pod = objects['pod']; subset = objects['endpoints']['subsets'][0]
                if case == 'uid': pod['metadata']['uid'] = 'stale'
                elif case == 'namespace': subset['addresses'][0]['targetRef']['namespace'] = 'other'
                elif case == 'selector': pod['metadata']['labels'] = {'other': 'label'}
                elif case == 'ip': pod['status']['podIP'] = '10.42.0.4'
                elif case == 'port': subset['ports'][0]['port'] = 443
                elif case == 'service-port': objects['service']['spec']['ports'][0]['targetPort'] = 9443
                elif case == 'not-ready': subset['notReadyAddresses'] = subset.pop('addresses')
                elif case == 'path': subset['addresses'][0]['targetRef']['name'] = '../other'
                elif case == 'terminating': pod['metadata']['deletionTimestamp'] = 'now'
                get, calls = self.request(objects)
                with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, get)
                self.assertFalse(any(c[1].startswith('--raw=') for c in calls))

    def test_body_must_be_exact_and_pod_identity_must_survive_probe(self):
        for body in (b'', b'ok\n', b'OK', b'healthy'):
            with self.subTest(body=body):
                get, _ = self.request(fixture(), body)
                with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, get)
        get, _ = self.request(fixture(), replace_after=True)
        with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, get)

    def test_all_ready_targets_must_pass_with_bounded_cardinality(self):
        objects = fixture(); subset = objects['endpoints']['subsets'][0]
        for number in range(8):
            address = copy.deepcopy(subset['addresses'][0]); address['targetRef']['name'] += str(number)
            subset['addresses'].append(address)
        get, calls = self.request(objects)
        with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, get)
        self.assertEqual(len(calls), 2)
        objects = fixture(); extra = copy.deepcopy(objects['endpoints']['subsets'][0]['addresses'][0])
        extra['targetRef']['name'] = 'agent-hook-b'; objects['endpoints']['subsets'][0]['addresses'].append(extra)
        calls = []
        def request(args, deadline):
            calls.append(args)
            if args[1].startswith('--raw='): return b'ok' if 'agent-hook-a:' in args[1] else b'failed'
            value = copy.deepcopy(objects[args[1]])
            if args[1] == 'pod': value['metadata']['name'] = args[2]
            return json.dumps(value).encode()
        with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, request)
        self.assertEqual(sum(c[1].startswith('--raw=') for c in calls), 2)

    def test_api_denial_and_timeout_fail_without_emitting_response(self):
        args = ['get', '--raw=/fixed']
        with patch.object(HEALTH.time, 'monotonic', return_value=10):
            with patch.object(HEALTH.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'private', b'private')) as run:
                with self.assertRaisesRegex(HEALTH.Unavailable, 'failed or was denied'): HEALTH.kubectl(args, 12)
                self.assertEqual(run.call_args.kwargs['timeout'], 2)
                self.assertIn('--request-timeout=3s', run.call_args.args[0])
                self.assertFalse(any('insecure' in arg for arg in run.call_args.args[0]))
            with patch.object(HEALTH.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 4)):
                with self.assertRaisesRegex(HEALTH.Unavailable, 'timed out'): HEALTH.kubectl(args, 20)
            with patch.object(HEALTH.subprocess, 'run') as run:
                with self.assertRaises(HEALTH.Unavailable): HEALTH.kubectl(args, 9)
                run.assert_not_called()

    def test_invalid_object_selector_and_conflicting_references_fail(self):
        for case in ('object', 'selector', 'conflicting'):
            with self.subTest(case=case):
                objects = fixture()
                if case == 'object': objects['service']['metadata']['namespace'] = 'other'
                elif case == 'selector': objects['service']['spec']['selector'] = {}
                else:
                    addresses = objects['endpoints']['subsets'][0]['addresses']
                    extra = copy.deepcopy(addresses[0]); extra['targetRef']['uid'] = 'different'
                    addresses.append(extra)
                get, calls = self.request(objects)
                with self.assertRaises(HEALTH.Unavailable): HEALTH.probe_once(100, get)
                self.assertFalse(any(c[1].startswith('--raw=') for c in calls))

    def test_main_success_and_request_exhausting_total_deadline(self):
        with patch.object(HEALTH, 'probe_once', return_value=1), patch('sys.stdout'):
            self.assertEqual(HEALTH.main(), 0)
        clock = [0]
        def exhausted(deadline):
            clock[0] = deadline
            raise HEALTH.Unavailable('request used remaining deadline')
        with patch.object(HEALTH.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(HEALTH, 'probe_once', side_effect=exhausted), \
                patch.object(HEALTH.time, 'sleep') as sleep, patch('sys.stderr'):
            self.assertEqual(HEALTH.main(), 1)
            sleep.assert_not_called()

    def test_retry_budget_is_total_and_failure_is_closed(self):
        clock = [0]
        def sleep(seconds): clock[0] += seconds
        with patch.object(HEALTH.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(HEALTH.time, 'sleep', side_effect=sleep), \
                patch.object(HEALTH, 'probe_once', side_effect=HEALTH.Unavailable('unavailable')) as probe, \
                patch('sys.stderr'):
            self.assertEqual(HEALTH.main(), 1)
        self.assertEqual(clock[0], HEALTH.TOTAL_SECONDS)
        self.assertEqual(probe.call_count, HEALTH.TOTAL_SECONDS)
