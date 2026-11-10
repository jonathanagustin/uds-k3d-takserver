# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('transfer', Path(__file__).parent / 'velero-ownership/transfer.py')
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


def agent(owner=T.LOCAL):
    return {'metadata': {'name': 'node-agent', 'namespace': 'velero', 'uid': 'agent-uid',
                         'resourceVersion': '12', 'generation': 1,
                         'annotations': {'meta.helm.sh/release-name': owner[0], 'meta.helm.sh/release-namespace': owner[1]},
                         'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
            'spec': {'selector': {'matchLabels': {'name': 'node-agent'}}},
            'status': {'desiredNumberScheduled': 1, 'numberReady': 1, 'numberAvailable': 1,
                       'updatedNumberScheduled': 1, 'observedGeneration': 1}}


class API:
    def __init__(self):
        self.ds = agent()
        self.writes = []
        self.busy = {kind: {'items': []} for kind in (*T.TERMINAL, 'schedules.velero.io', 'pods')}
        self.local_recorded, self.core_recorded = True, False
        self.config = None
        self.receipt = {'clusterUID': 'cluster', 'markerUID': 'marker'}

    def guard(self, context, command):
        return dict(self.receipt)

    def command(self, args, input_text=None):
        if args[0] == 'uds':
            recorded = self.local_recorded if args[8] == T.LOCAL[0] else self.core_recorded
            return json.dumps({'kind': 'DaemonSet', 'metadata': {'name': 'node-agent', 'namespace': 'velero'}}) if recorded else ''
        action, kind = args[3:5]
        if action == 'get':
            if kind == 'daemonset':
                return json.dumps(self.ds)
            if kind == 'configmap':
                if '--ignore-not-found' in args:
                    return json.dumps(self.config) if self.config else ''
                owner = T.LOCAL if args[5] == 'node-agent-config' else T.CORE
                return json.dumps({'metadata': {'name': args[5], 'namespace': 'velero', 'uid': 'config-source', 'resourceVersion': '1',
                                               'annotations': {'meta.helm.sh/release-name': owner[0], 'meta.helm.sh/release-namespace': owner[1]},
                                               'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
                                   'data': {'node-agent-config.json': json.dumps(T.PAYLOAD)}})
            return json.dumps(self.busy[kind])
        self.writes.append((args, input_text))
        if action == 'patch':
            for op in json.loads(input_text):
                key = op['path'].split('/')[-1].replace('~1', '/')
                target = self.ds['metadata'] if op['path'].count('/') == 2 else self.ds['metadata'][op['path'].split('/')[2]]
                if op['op'] == 'test':
                    if target[key] != op['value']:
                        raise ValueError('API conflict')
                else:
                    target[key] = op['value']
            self.ds['metadata']['resourceVersion'] = '13'
            return json.dumps(self.ds)
        self.config = json.loads(input_text)
        self.config['metadata'].update(uid='config-uid', resourceVersion='1')
        return json.dumps(self.config)

    def driver(self):
        return T.Transfer('k3d-uds', 'agent-uid', self.command, self.guard)


class TransferTests(unittest.TestCase):
    def test_patch_has_exact_compare_and_swap_and_no_spec_changes(self):
        patch = T.ownership_patch(agent(), 'agent-uid', T.LOCAL, T.CORE)
        tests = {op['path']: op['value'] for op in patch if op['op'] == 'test'}
        self.assertEqual(tests['/metadata/resourceVersion'], '12')
        self.assertEqual(tests['/metadata/uid'], 'agent-uid')
        self.assertEqual(tests['/metadata/labels/app.kubernetes.io~1managed-by'], 'Helm')
        self.assertTrue(all(op['path'].startswith('/metadata/') for op in patch))

    def test_forward_real_commands_and_actual_state_idempotence(self):
        api = API()
        result = api.driver().transfer(T.LOCAL, T.CORE)
        self.assertTrue(result['changed'])
        self.assertEqual(T.ownership(api.ds), T.CORE)
        self.assertFalse(api.driver().transfer(T.LOCAL, T.CORE)['changed'])
        self.assertEqual(len(api.writes), 1)

    def test_reverse_refuses_undetached_core_release(self):
        api = API()
        api.ds = agent(T.CORE)
        api.ds['metadata']['annotations']['helm.sh/resource-policy'] = 'keep'
        api.local_recorded, api.core_recorded = False, True
        with self.assertRaisesRegex(ValueError, 'Core still records'):
            api.driver().transfer(T.CORE, T.LOCAL)
        self.assertFalse(api.writes)
        api.core_recorded = False
        self.assertTrue(api.driver().transfer(T.CORE, T.LOCAL)['changed'])

    def test_busy_unknown_and_terminating_refuse_without_writes(self):
        for kind in T.TERMINAL:
            for phase in ('InProgress', 'NewUnknownPhase'):
                with self.subTest(kind=kind, phase=phase):
                    api = API()
                    api.busy[kind]['items'] = [{'metadata': {}, 'status': {'phase': phase}}]
                    with self.assertRaises(ValueError):
                        api.driver().transfer(T.LOCAL, T.CORE)
                    self.assertFalse(api.writes)
        api = API()
        api.busy['pods']['items'] = [{'metadata': {'labels': {'app.kubernetes.io/component': 'velero-data-mover'}}, 'status': {'phase': 'Running'}}]
        with self.assertRaises(ValueError):
            api.driver().transfer(T.LOCAL, T.CORE)
        self.assertFalse(api.writes)

    def test_wrong_owner_uid_incomplete_terminating_agent_refused(self):
        for mutation in (
            lambda ds: ds['metadata'].update(uid='other'),
            lambda ds: ds['metadata'].update(deletionTimestamp='now'),
            lambda ds: ds['metadata']['annotations'].update({'helm.sh/resource-policy': 'unknown'}),
            lambda ds: ds['status'].update(numberReady=0),
            lambda ds: ds['metadata']['annotations'].update({'meta.helm.sh/release-name': 'unknown'}),
        ):
            api = API()
            mutation(api.ds)
            with self.assertRaises(ValueError):
                api.driver().transfer(T.LOCAL, T.CORE)
            self.assertFalse(api.writes)

    def test_changed_cluster_receipt_refused(self):
        api = API()
        driver = api.driver()
        api.receipt['markerUID'] = 'other'
        with self.assertRaises(ValueError):
            driver.transfer(T.LOCAL, T.CORE)
        self.assertFalse(api.writes)

    def test_local_config_real_create_and_idempotent_verification(self):
        api = API()
        api.ds = agent(T.CORE)
        api.ds['metadata']['annotations']['helm.sh/resource-policy'] = 'keep'
        self.assertTrue(api.driver().local_config()['changed'])
        self.assertFalse(api.driver().local_config()['changed'])
        self.assertEqual(json.loads(api.config['data']['node-agent-config.json']), T.PAYLOAD)
        api.config['metadata']['deletionTimestamp'] = 'now'
        with self.assertRaises(ValueError):
            api.driver().local_config()
        self.assertEqual(len(api.writes), 1)

    def test_api_conflict_is_not_retried_or_rolled_back(self):
        api = API()
        original = api.command
        def command(args, input_text=None):
            if args[0] == 'kubectl' and args[3] == 'patch':
                api.ds['metadata']['resourceVersion'] = '99'
            return original(args, input_text)
        driver = T.Transfer('k3d-uds', 'agent-uid', command, api.guard)
        with self.assertRaisesRegex(ValueError, 'API conflict'):
            driver.transfer(T.LOCAL, T.CORE)
        self.assertEqual(T.ownership(api.ds), T.LOCAL)
        self.assertEqual(len(api.writes), 1)


if __name__ == '__main__':
    unittest.main()
