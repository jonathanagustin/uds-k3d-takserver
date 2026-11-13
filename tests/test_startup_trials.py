# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline startup cohort fixtures only; no cluster, JVM, or timing experiment."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bench import startup_trials as trial, jvm_metrics as jvm
from tests.test_jvm_metrics import pod, fake_commands, metrics


def application(app, warm=False):
    p = pod(); p['metadata'].update(name=app+'-abc', labels={'app': app}, creationTimestamp='2024-01-01T00:00:20Z' if warm else '2024-01-01T00:00:00Z')
    digit = '1' if app == jvm.APPS[0] else '2'
    p['metadata']['uid'] = digit*8+'-'+digit*4+'-'+digit*4+'-'+digit*4+'-'+('a' if warm else digit)*12
    p['spec'].update(nodeName='node-a', containers=[{'name': app, 'image': 'example/image:stable'}])
    status = p['status']['containerStatuses'][1]; status['name'] = app
    status['containerID'] = 'containerd://'+('d' if warm else digit)*64
    status['state']['running']['startedAt'] = '2024-01-01T00:00:20Z' if warm else '2024-01-01T00:00:00Z'
    p['status']['conditions'][0]['lastTransitionTime'] = '2024-01-01T00:00:26Z' if warm else '2024-01-01T00:00:06Z'
    p['status']['containerStatuses'] = [status]
    return p


class Commands:
    def __init__(self, state):
        self.state = state; self.calls = []
    def run(self, args, limit):
        self.calls.append(args)
        if args[:2] == ['get', 'namespace']: value = {'metadata': {'uid': 'cluster-a'}}
        elif args[:2] == ['get', 'nodes']:
            value = {'items': [{'metadata': {'name': 'node-a', 'uid': 'node-uid-a'}, 'status': {
                'nodeInfo': {'architecture': 'amd64', 'operatingSystem': 'linux', 'kernelVersion': '6.8.0',
                             'osImage': 'Ubuntu LTS', 'containerRuntimeVersion': 'containerd://2.0', 'kubeletVersion': 'v1.35.0'},
                'images': [{'names': ['example/image:stable'], 'sizeBytes': 100}]}}]}
        elif args[:2] == ['get', 'deployments']:
            value = {'items': [] if self.state == 'empty' else [{'metadata': {'name': app, 'uid': app+'-deployment'},
                'spec': {'template': {'metadata': {}, 'spec': {'containers': [{'name': app, 'image': 'example/image:stable',
                  'env': [{'name': 'PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'password', 'key': 'value'}}}]}],
                  'volumes': [{'configMap': {'name': 'settings'}}]}}}} for app in jvm.APPS]}
        elif args[:2] == ['get', 'pods']: value = {'items': [] if self.state == 'empty' else [application(app, self.state == 'warm') for app in jvm.APPS]}
        elif args[:2] == ['get', 'configmap']: value = {'metadata': {'uid': 'config-a', 'resourceVersion': '1'}, 'data': {'password': 'PRIVATE_SENTINEL'}}
        elif args[:2] == ['get', 'secret']:
            assert args[-1] == 'jsonpath={.metadata.uid}{" "}{.metadata.resourceVersion}'
            return b'secret-a 1'
        elif args[:2] == ['get', 'events']: value = {'items': []}
        elif args[0] == 'logs': return ('2024-01-01T00:00:'+('25' if self.state == 'warm' else '05')+'.123Z Started TAK Server\nPRIVATE LOG SENTINEL\n').encode()
        else: raise AssertionError('unexpected fixture command')
        result = json.dumps(value).encode(); assert len(result) <= limit; return result


def observation(app, context, warm=False):
    p = application(app, warm)
    body = metrics(start='1704067221' if warm else '1704067201')
    base = 1704067220 if warm else 1704067200
    with patch.object(jvm.time, 'time', side_effect=[base+7, base+7.01, base+7.02, base+7.03]), \
            patch.object(jvm.time, 'monotonic', side_effect=[100, 100.01, 100.02, 100.03]):
        return jvm.observe(app, context, fake_commands(first=p, last=copy.deepcopy(p), bodies=[body, body]))


def pair():
    with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:00Z'):
        initial = trial.begin('owned', 'cohort-a', {'source': 'b'*64, 'config': 'a'*64}, Commands('empty'))
    with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:10Z'):
        cold = trial.finish(initial, 'cold', Commands('cold'), observation)
        warm_start = trial.begin('owned', 'cohort-a', {'source': 'b'*64, 'config': 'a'*64}, Commands('cold'), observation)
    with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:30Z'):
        warm = trial.finish(warm_start, 'warm', Commands('warm'), lambda app, context: observation(app, context, True))
    return cold, warm


class StartupTrials(unittest.TestCase):
    def test_actual_capture_path_uses_numeric_existing_observer_and_new_incarnations(self):
        cold, warm = pair(); verdict = trial.validate_pair(cold, warm)
        self.assertTrue(verdict['accepted']); self.assertEqual(warm['warm_s'], 6)
        for app in jvm.APPS:
            self.assertEqual(cold['phases'][app]['jvm_to_log_s'], 4.123)
            self.assertNotEqual(cold['phases'][app]['evidence']['pod_uid'], warm['phases'][app]['evidence']['pod_uid'])
        serialized = json.dumps([cold, warm, verdict])
        self.assertNotIn('PRIVATE_SENTINEL', serialized); self.assertNotIn('PRIVATE LOG SENTINEL', serialized)
        self.assertIn('not page-cache', cold['begin']['cache_scope'])

    def test_pair_rejects_missing_warm_and_drift_without_changing_old_records(self):
        cold, warm = pair()
        for name in ['same-jvm', 'same-pod', 'missing-warm', 'marker-after-ready', 'changed-join', 'config', 'image', 'node', 'platform', 'cohort', 'bindings', 'clock', 'created', 'cache-missing', 'counter-reset', 'sample-clock', 'future-sample', 'reversed-begin', 'observer-binding', 'source-missing', 'pair-order', 'old-created']:
            with self.subTest(name=name):
                c, w = copy.deepcopy(cold), copy.deepcopy(warm); app = jvm.APPS[0]
                if name == 'same-jvm': w['phases'][app]['jvm_observation']['jvm_start_time_unix_ms'] = c['phases'][app]['jvm_observation']['jvm_start_time_unix_ms']
                elif name == 'same-pod': w['snapshot']['identities'][app]['pod_uid'] = c['snapshot']['identities'][app]['pod_uid']
                elif name == 'missing-warm': w['warm_s'] = None
                elif name == 'marker-after-ready': w['phases'][app]['evidence']['startup_log_at'] = '2024-01-01T00:00:26.001Z'
                elif name == 'changed-join': w['phases'][app]['jvm_to_log_s'] = 999
                elif name == 'config': w['snapshot']['config_sha256'][app] = 'b'*64
                elif name == 'image': w['snapshot']['identities'][app]['image_id'] = 'sha256:'+'d'*64
                elif name == 'node': w['snapshot']['identities'][app]['node_uid'] = 'node-other'
                elif name == 'platform': w['snapshot']['platform'][0]['kernel'] = 'other'
                elif name == 'cohort': w['begin']['cohort'] = 'other'; w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'bindings': w['begin']['bindings']['config'] = 'b'*64; w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'clock': w['observed_finished_at'] = '2024-01-01T00:00:01Z'
                elif name == 'created': w['pod_created_at'][app] = '2024-01-01T00:01:00Z'
                elif name == 'cache-missing': w['begin']['snapshot'].pop('reported_image_cache'); w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'counter-reset': w['phases'][app]['jvm_observation']['samples'][1]['jvm_classes_loaded_total'] = 1
                elif name == 'sample-clock': w['phases'][app]['jvm_observation']['samples'][0]['observed_end_unix'] += 2
                elif name == 'future-sample': w['phases'][app]['jvm_observation']['samples'][1]['observed_end_unix'] = 1704067250
                elif name == 'reversed-begin': w['begin']['observed_started_at'] = '2024-01-01T00:00:15Z'; w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'observer-binding': w['begin']['jvm_observer_sha256'] = 'f'*64; w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'source-missing': w['begin']['bindings'].pop('source'); w['begin_sha256'] = trial.digest(w['begin'])
                elif name == 'pair-order': c['observed_finished_at'] = '2024-01-01T00:00:12Z'
                elif name == 'old-created': w['pod_created_at'][app] = '2024-01-01T00:00:09Z'
                with self.assertRaises((trial.Invalid, KeyError)): trial.validate_pair(c, w)
        self.assertTrue(trial.validate_pair(cold, warm)['accepted'])

    def test_begin_cold_refuses_existing_apps_and_config_secrets_are_never_output(self):
        with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:10Z'):
            initial = trial.begin('owned', 'cohort-a', {'source': 'b'*64, 'config': 'a'*64}, Commands('cold'), observation)
        with self.assertRaises(trial.Invalid): trial.finish(initial, 'cold', Commands('cold'), observation)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(initial))
        self.assertEqual(trial.references({'imagePullSecrets': [{'name': 'pull-key'}]})['secrets'], {'pull-key'})

    def test_phase_identity_and_init_chronology_cannot_be_relabelled(self):
        cold, warm = pair(); app = jvm.APPS[0]
        for mutation in ('context', 'sample-start', 'container-start', 'late-init', 'cold-warm-value'):
            with self.subTest(mutation=mutation):
                c, w = copy.deepcopy(cold), copy.deepcopy(warm)
                phase = w['phases'][app]
                if mutation == 'context': phase['jvm_observation']['context'] = 'different'
                elif mutation == 'sample-start': phase['jvm_observation']['samples'][0]['jvm_start_time_unix_ms'] += 1
                elif mutation == 'container-start':
                    for value in (phase['evidence'], phase['jvm_observation']['identity'], w['snapshot']['identities'][app]):
                        value['container_started_at'] = '2024-01-01T00:00:23Z'
                elif mutation == 'late-init':
                    phase['declared_init_names'] = ['setup']
                    phase['inits'] = [{'name': 'setup', 'seconds': 1}]
                    phase['evidence']['init_intervals'] = [{'name': 'setup', 'started_at': '2024-01-01T00:00:25Z', 'finished_at': '2024-01-01T00:00:26Z'}]
                else: c['warm_s'] = 6
                with self.assertRaises(trial.Invalid): trial.validate_pair(c, w)

    def test_private_cli_outputs_are_first_write_only(self):
        cold, warm = pair()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); root.chmod(0o700)
            (root/'cold').write_text(json.dumps(cold)); (root/'warm').write_text(json.dumps(warm))
            argv = ['startup', 'pair', '--cold', str(root/'cold'), '--warm', str(root/'warm'), '--output', str(root/'pair')]
            with patch('sys.argv', argv): self.assertEqual(trial.main(), 0)
            original = (root/'pair').read_bytes()
            self.assertTrue(json.loads(original)['accepted'])
            self.assertEqual((root/'pair').stat().st_mode & 0o777, 0o600)
            with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()): self.assertEqual(trial.main(), 1)
            self.assertEqual((root/'pair').read_bytes(), original)

    def test_finish_rejects_ready_or_configuration_change_during_collection(self):
        class Drifting(Commands):
            def __init__(self, kind):
                super().__init__('warm'); self.kind = kind; self.node_reads = 0
            def run(self, args, limit):
                if args[:2] == ['get', 'namespace']: self.node_reads += 1
                value = super().run(args, limit)
                if self.node_reads > 1 and args[:2] == ['get', 'pods'] and self.kind == 'ready':
                    body = json.loads(value)
                    body['items'][0]['status']['conditions'][0]['status'] = 'False'
                    return json.dumps(body).encode()
                if self.node_reads > 1 and args[:2] == ['get', 'secret'] and self.kind == 'secret': return b'secret-a 2'
                return value
        cold, warm = pair()
        for kind in ('ready', 'secret'):
            with self.subTest(kind=kind), patch.object(trial, 'stamp', return_value='2024-01-01T00:00:30Z'):
                with self.assertRaises(trial.Invalid): trial.finish(warm['begin'], 'warm', Drifting(kind), lambda app, context: observation(app, context, True))

    def test_schema_duplicates_symlinks_and_errors_do_not_export_private_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); root.chmod(0o700)
            f = root/'input.json'; f.write_text('{"x":1,"x":2}')
            with self.assertRaises(trial.Invalid): trial.read_file(f)
            link = root/'link'; link.symlink_to(f)
            with self.assertRaises(trial.Invalid): trial.read_file(link)
            out = io.StringIO()
            with patch('sys.argv', ['startup', 'begin', '--context', 'owned', '--cohort', 'c', '--bindings', str(f), '--output', str(root/'output')]), contextlib.redirect_stdout(out):
                self.assertEqual(trial.main(), 1)
            self.assertNotIn('PRIVATE', out.getvalue()); self.assertFalse((root/'output').exists())
            f.write_text('{"config":"'+('a'*64)+'"}')
            out = io.StringIO()
            with patch('sys.argv', ['startup', 'begin', '--context', 'owned', '--cohort', 'c', '--bindings', str(f), '--output', str(root/'output')]), patch.object(trial, 'begin', side_effect=RuntimeError('PRIVATE_RAW_EXCEPTION')), contextlib.redirect_stdout(out):
                self.assertEqual(trial.main(), 1)
            self.assertNotIn('PRIVATE_RAW_EXCEPTION', out.getvalue())
