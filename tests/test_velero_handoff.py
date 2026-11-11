# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Negative handoff evidence cases; never connect to a cluster or mutate Helm."""
import copy
import os
import hashlib
import re
import subprocess
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
    result = {'retiredCoreConfig': None, 'clusterUID': 'test-cluster', 'daemonset': ds, 'agentConfig': cm,
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
    def test_local_evidence_requires_manifest_and_live_core_config_absence(self):
        baseline = observe.validate(snapshot(True), 'local-before')
        for mode in ('manifest', 'live', 'unobserved'):
            value = snapshot(True)
            if mode == 'manifest':
                value['coreManifest'].append({'kind': 'ConfigMap', 'metadata': {'name': 'velero-node-agent-config', 'namespace': 'velero'}})
            elif mode == 'live':
                value['retiredCoreConfig'] = {'metadata': {'name': 'velero-node-agent-config', 'deletionTimestamp': 'now'}}
            else:
                del value['retiredCoreConfig']
            with self.assertRaises(ValueError):
                observe.validate(value, 'local-after', baseline)

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

    def test_all_candidate_variants_pause_only_the_known_schedule_without_changing_defaults(self):
        original = yaml.safe_load((ROOT / 'bundle/full/uds-bundle.yaml').read_text())
        before = copy.deepcopy(original)
        exemption = next(d for d in documents(True) if d['kind'] == 'Exemption')
        variants = module('candidate').variants(original, exemption)
        self.assertEqual(original, before)
        for name, value in variants.items():
            with self.subTest(variant=name):
                package = next(p for p in value['packages'] if p['name'] == 'core-backup-restore')
                values = package['overrides']['velero']['velero']['values']
                schedules = [v for v in values if v['path'].startswith('schedules')]
                self.assertEqual(schedules, [{'path': 'schedules.udsbackup.paused', 'value': True}])
        for path in ('schedules', 'schedules.udsbackup', 'schedules.udsbackup.paused'):
            value = copy.deepcopy(original)
            package = next(p for p in value['packages'] if p['name'] == 'core-backup-restore')
            package['overrides']['velero']['velero']['values'].append({'path': path, 'value': {}})
            with self.subTest(conflict=path), self.assertRaises(ValueError):
                prepare(value, exemption)

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

    def test_terminating_agent_resources_cannot_be_ready_evidence(self):
        for local in (False, True):
            stage = 'local-before' if local else 'core-ready'
            observe.validate(snapshot(local), stage)
            for resource in ('daemonset', 'pod', 'config'):
                with self.subTest(local=local, resource=resource):
                    value = snapshot(local)
                    obj = {'daemonset': value['daemonset'], 'pod': value['pods']['items'][0],
                           'config': value['agentConfig']}[resource]
                    # Kubernetes may retain Ready status while deletion is in
                    # progress. Ownership and last-ready status are insufficient.
                    obj['metadata']['deletionTimestamp'] = '2026-11-09T00:00:30Z'
                    with self.assertRaisesRegex(ValueError, 'terminating'):
                        observe.validate(value, stage)

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




@unittest.skipUnless(os.environ.get('STAGED_VELERO_CHART_ARCHIVE') and os.environ.get('STAGED_VELERO_CORE_VALUES'),
                     'opt-in verified official chart/Core values required for real Helm proof')
class OfficialScheduleRender(unittest.TestCase):
    def test_real_pinned_chart_pauses_default_schedule_at_creation_without_other_changes(self):
        archive = Path(os.environ['STAGED_VELERO_CHART_ARCHIVE'])
        core = Path(os.environ['STAGED_VELERO_CORE_VALUES'])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         'fe4acd70a0123c369e7af7064457b4ffdddebee413e2bb01976a4fe07c471773')
        self.assertEqual(hashlib.sha256(core.read_bytes()).hexdigest(),
                         '492018cfaaab198615fba8d448a2a87d568eb18658dac3a4642bdd70ef6aa9a9')
        # Only bucket credential placeholders need nonsecret fixtures for Helm;
        # schedule content is consumed unchanged from official Core 1.16 values.
        text = re.sub(r'{{\.Variables\.[A-Z_]+}}', 'fixture', core.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            values = Path(temporary) / 'values.yaml'; values.write_text(text)
            original = yaml.safe_load((ROOT / 'bundle/full/uds-bundle.yaml').read_text())
            exemption = next(d for d in documents(True) if d['kind'] == 'Exemption')
            variants = module('candidate').variants(original, exemption)
            argv = ['helm', 'template', 'velero', str(archive), '--namespace', 'velero',
                    '-f', str(values), '--show-only', 'templates/schedule.yaml']
            baseline = [d for d in yaml.safe_load_all(subprocess.check_output(argv, text=True)) if d]
            self.assertEqual(len(baseline), 1)
            self.assertEqual(baseline[0]['metadata']['name'], 'velero-udsbackup')
            self.assertNotIn('paused', baseline[0]['spec'])
            for name, candidate in variants.items():
                package = next(p for p in candidate['packages'] if p['name'] == 'core-backup-restore')
                entry = next(v for v in package['overrides']['velero']['velero']['values']
                             if v['path'] == 'schedules.udsbackup.paused')
                rendered = [d for d in yaml.safe_load_all(subprocess.check_output(
                    [*argv, '--set', entry['path'] + '=' + str(entry['value']).lower()], text=True)) if d]
                with self.subTest(variant=name):
                    self.assertIs(rendered[0]['spec'].pop('paused'), True)
                    self.assertEqual(rendered, baseline)


if __name__ == '__main__':
    unittest.main()
