# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Negative handoff evidence cases; never connect to a cluster or mutate Helm."""
import copy
import importlib.util
import json
import io
import contextlib
import tempfile
from unittest import mock
from pathlib import Path
import unittest
import yaml
from tests.test_filesystem_backup_owner import documents

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('velero_' + name, ROOT / 'tests/velero-ownership' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


prepare = module('prepare').prepare
observe = module('observe')


def owned(name, local=False):
    release = observe.LOCAL if local else observe.CORE
    return {'name': name, 'namespace': 'velero', 'uid': 'same-agent', 'generation': 2,
            'resourceVersion': '22', 'labels': {'app.kubernetes.io/managed-by': 'Helm'},
            'annotations': {'meta.helm.sh/release-name': release[0], 'meta.helm.sh/release-namespace': release[1], 'helm.sh/resource-policy': 'keep'}}


def snapshot(local=False):
    config = 'node-agent-config' if local else 'velero-node-agent-config'
    ds = {'kind': 'DaemonSet', 'metadata': owned('node-agent', local), 'spec': {'selector': {'matchLabels': {'name': 'node-agent'}}},
          'status': {'desiredNumberScheduled': 1, 'numberReady': 1, 'updatedNumberScheduled': 1, 'numberAvailable': 1, 'observedGeneration': 2}}
    cm = {'kind': 'ConfigMap', 'metadata': owned(config, local), 'data': {'node-agent-config.json': json.dumps({'privilegedFsBackup': True, 'podLabels': {'app.kubernetes.io/name': 'velero', 'app.kubernetes.io/component': 'velero-data-mover'}})}}
    result = {'clusterUID': 'test-cluster', 'daemonset': ds, 'agentConfig': cm,
              'pods': {'items': [{'metadata': {'ownerReferences': [{'uid': 'same-agent', 'controller': True}]}, 'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]}, 'spec': {'containers': [{'name': 'node-agent', 'args': ['--node-agent-configmap=' + config]}]}}]},
              'bootstrap': {'metadata': {'name': 'velero-node-agent-bootstrap'}, 'spec': {'exemptions': ['exact']}}, 'localExemption': {'metadata': {'name': 'velero-node-agent'}, 'spec': {'exemptions': ['exact']}},
              'coreManifest': [] if local else [ds, cm], 'localManifest': [ds, cm] if local else [],
              'readyAt': '2026-11-09T00:00:00+00:00',
              'backup': {'metadata': {'name': 'new-backup', 'creationTimestamp': '2026-11-09T00:01:00Z'}, 'status': {'phase': 'Completed'}},
              'restore': {'metadata': {'name': 'new-restore'}, 'spec': {'backupName': 'new-backup'}, 'status': {'phase': 'Completed'}}}
    for key, label, name in [('pvb', 'velero.io/backup-name', 'new-backup'), ('pvr', 'velero.io/restore-name', 'new-restore')]:
        result[key] = {'items': [{'metadata': {'name': key + '-' + ns, 'labels': {label: name}}, 'spec': {'pod': {'namespace': ns}, 'volume': 'data'}, 'status': {'phase': 'Completed'}} for ns in ('takserver', 'cloudtak')]}
    return result


class HandoffTests(unittest.TestCase):
    def test_owner_variable_default_and_early_zarf_values_file(self):
        package = yaml.safe_load((ROOT / 'zarf.yaml').read_text())
        variable = next(v for v in package['variables'] if v['name'] == 'FILESYSTEM_BACKUP_OWNER')
        self.assertEqual(variable['default'], 'local')
        switch = yaml.safe_load((ROOT / 'values/filesystem-backup-switch.yaml').read_text())
        self.assertEqual(switch['backup']['filesystem']['owner'], '###ZARF_VAR_FILESYSTEM_BACKUP_OWNER###')

    def test_preparation_preserves_bundle_custom_exemptions_and_default_inputs(self):
        bundle = yaml.safe_load((ROOT / 'bundle/full/uds-bundle.yaml').read_text())
        original = copy.deepcopy(bundle)
        exemption = next(d for d in documents(True) if d['kind'] == 'Exemption')
        custom = [{'name': 'already-present', 'exemptions': []}]
        bundle['packages'][0]['overrides']['uds-exemptions'] = {'uds-exemptions': {'values': [{'path': 'exemptions.custom', 'value': custom}]}}
        candidate = prepare(bundle, exemption)
        self.assertEqual(len(custom), 1)
        values = candidate['packages'][0]['overrides']['uds-exemptions']['uds-exemptions']['values']
        self.assertEqual(values[0]['value'][0], custom[0])
        self.assertEqual(values[0]['value'][1]['exemptions'], exemption['spec']['exemptions'])
        before = next(p for p in original['packages'] if p['name'] == 'core-backup-restore')['overrides']['velero']['velero']['values']
        after = next(p for p in candidate['packages'] if p['name'] == 'core-backup-restore')['overrides']['velero']['velero']['values']
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(next(v for v in after if v['path'] == 'nodeAgent')['value']['annotations'], {'helm.sh/resource-policy': 'keep'})
        with self.assertRaises(ValueError): prepare(candidate, exemption)
        bad = copy.deepcopy(original)
        bad['packages'][0]['ref'] = 'unreviewed'
        with self.assertRaises(ValueError): prepare(bad, exemption)

    def test_fresh_forward_and_reverse_are_distinct_accepted_observations(self):
        before = observe.validate(snapshot(True), 'local-before')
        self.assertFalse(before['backupRestore'])
        self.assertTrue(observe.validate(snapshot(), 'core-after', before)['backupRestore'])
        self.assertTrue(observe.validate(snapshot(True), 'local-after', before)['backupRestore'])
        self.assertTrue(observe.validate(snapshot(), 'fresh-core')['backupRestore'])

    def test_unknown_owner_replacement_selector_rollout_bootstrap_and_old_manifest_fail(self):
        baseline = {'clusterUID': 'test-cluster', 'daemonsetUID': 'same-agent'}
        changes = [
            lambda s: s['daemonset']['metadata']['annotations'].update({'meta.helm.sh/release-name': 'foreign'}),
            lambda s: s['daemonset']['metadata'].update(uid='replacement'),
            lambda s: s.update(clusterUID='another-cluster'),
            lambda s: s['daemonset']['spec'].update(selector={'matchLabels': {'wrong': 'selector'}}),
            lambda s: s['daemonset']['status'].update(numberReady=0),
            lambda s: s['pods']['items'][0]['status'].update(phase='Pending'),
            lambda s: s['pods']['items'][0]['spec']['containers'][0].update(args=['--node-agent-configmap=old']),
            lambda s: s['bootstrap'].update(spec={'exemptions': ['broadened']}),
            lambda s: s['localManifest'].append(copy.deepcopy(s['daemonset'])),
            lambda s: s['daemonset']['metadata']['annotations'].pop('helm.sh/resource-policy'),
        ]
        for change in changes:
            with self.subTest(change=change):
                value = snapshot(); change(value)
                with self.assertRaises(ValueError): observe.validate(value, 'core-after', baseline)

    def test_stale_wrong_backup_partial_or_missing_volume_and_secret_manifest_fail(self):
        for mutate in [lambda s: s['backup']['metadata'].update(creationTimestamp='2026-11-08T00:00:00Z'),
                       lambda s: s['restore']['spec'].update(backupName='wrong'),
                       lambda s: s['backup']['status'].update(errors=1),
                       lambda s: s['restore']['status'].update(warnings=1),
                       lambda s: s['pvr']['items'].pop(),
                       lambda s: s['pvb']['items'][0]['status'].update(phase='Failed'),
                       lambda s: s['pvr']['items'][0]['metadata']['labels'].update({'velero.io/restore-name': 'old'})]:
            value = snapshot(); mutate(value)
            with self.assertRaises(ValueError): observe.validate(value, 'core-after')
        private = 'kind: Secret\nmetadata:\n  name: node-agent\n  namespace: velero\ndata:\n  token: DO_NOT_RETAIN\n'
        self.assertEqual(observe.resources(private), [])

    def test_reverse_refuses_unrelated_or_stale_forward_proof_before_cluster_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = observe.validate(snapshot(True), 'local-before')
            (directory / 'local-before.json').write_text(json.dumps(before))
            forward = observe.validate(snapshot(), 'core-after', before)
            forward['clusterUID'] = 'another-cluster'
            (directory / 'core-after.json').write_text(json.dumps(forward))
            argv = ['observe.py', '--context', 'ephemeral', '--stage', 'local-ready', '--directory', temporary]
            with mock.patch('sys.argv', argv), mock.patch.object(observe.subprocess, 'run') as command:
                with self.assertRaises(ValueError): observe.main()
                command.assert_not_called()

    def test_cli_only_reads_and_refuses_proof_overwrite_without_leaking_secrets(self):
        value = snapshot()
        baseline = observe.validate(snapshot(True), 'local-before')
        def read_command(argv, **kwargs):
            self.assertEqual(kwargs['timeout'], 45)
            self.assertNotIn('apply', argv)
            self.assertNotIn('patch', argv)
            self.assertNotIn('delete', argv)
            if argv[0] == 'helm':
                self.assertEqual(argv[3:5], ['get', 'manifest'])
                records = value['localManifest'] if argv[5] == observe.LOCAL[0] else value['coreManifest']
                output = yaml.safe_dump_all(records + [{'kind': 'Secret', 'metadata': {'name': 'secret', 'namespace': 'velero'}, 'data': {'password': 'DO_NOT_RETAIN'}}])
            else:
                self.assertEqual(argv[3], 'get')
                kind = argv[4]
                result = {'namespace': {'metadata': {'uid': value['clusterUID']}}, 'daemonset': value['daemonset'],
                          'pods': value['pods'], 'configmap': value['agentConfig']}.get(kind)
                if kind == 'exemption':
                    result = value['bootstrap'] if argv[5] == 'velero-node-agent-bootstrap' else value['localExemption']
                output = json.dumps(result)
            return type('Result', (), {'returncode': 0, 'stdout': output})()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'local-before.json').write_text(json.dumps(baseline))
            argv = ['observe.py', '--context', 'ephemeral', '--stage', 'core-ready', '--directory', temporary]
            output = io.StringIO()
            with mock.patch('sys.argv', argv), mock.patch.object(observe.subprocess, 'run', side_effect=read_command), contextlib.redirect_stdout(output):
                observe.main()
                with self.assertRaises(FileExistsError): observe.main()
            saved = (directory / 'core-ready.json').read_text()
            self.assertNotIn('DO_NOT_RETAIN', saved + output.getvalue())
            self.assertEqual(json.loads(saved)['daemonsetUID'], 'same-agent')


if __name__ == '__main__':
    unittest.main()
