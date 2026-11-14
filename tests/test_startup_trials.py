# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline startup cohort fixtures only; no cluster, JVM, or timing experiment."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml
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


def pair(commands=Commands):
    with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:00Z'):
        initial = trial.begin('owned', 'cohort-a', {'source': 'b'*64, 'config': 'a'*64}, commands('empty'))
    with patch.object(trial, 'stamp', side_effect=['2024-01-01T00:00:06.500Z', '2024-01-01T00:00:10Z']):
        cold = trial.finish(initial, 'cold', commands('cold'), observation)
    with patch.object(trial, 'stamp', return_value='2024-01-01T00:00:10Z'):
        warm_start = trial.begin('owned', 'cohort-a', {'source': 'b'*64, 'config': 'a'*64}, commands('cold'), observation)
    with patch.object(trial, 'stamp', side_effect=['2024-01-01T00:00:26.500Z', '2024-01-01T00:00:30Z']):
        warm = trial.finish(warm_start, 'warm', commands('warm'), lambda app, context: observation(app, context, True))
    return cold, warm


class StartupTrials(unittest.TestCase):
    def test_finish_retains_actual_join_rejection_without_accepting_timing(self):
        cold, warm = pair()
        class LateMarker(Commands):
            def run(self, args, limit):
                if args[0] == 'logs':
                    second = '26' if self.state == 'warm' else '06'
                    return f'2024-01-01T00:00:{second}.001Z Started TAK Server\nPRIVATE_LOG\n'.encode()
                return super().run(args, limit)
        for mode, record in (('cold', cold), ('warm', warm)):
            with self.subTest(mode=mode):
                with self.assertRaises(trial.PhaseUnavailable) as caught:
                    trial.finish(record['begin'], mode, LateMarker(mode),
                                 lambda app, context: observation(app, context, mode == 'warm'))
                self.assertEqual(str(caught.exception), 'phase_unavailable')
                result = trial.failure_diagnostic(caught.exception)
                self.assertEqual(result['phase'], {'app': jvm.APPS[0], 'stage': 'finish-join',
                                                   'reason': 'marker_after_ready'})
                self.assertNotIn('PRIVATE', json.dumps(result))

    def test_begin_and_finish_observer_failures_keep_only_fixed_phase_facts(self):
        cold, _ = pair()
        for reason in ('metrics_missing', 'command_failed', 'pod_incarnation_changed',
                       'PRIVATE_REASON', None, {'PRIVATE': 'PAYLOAD'}):
            for stage in ('begin-observer', 'finish-join'):
                with self.subTest(reason=reason, stage=stage):
                    def unavailable(app, context):
                        return {'available': False, 'reason': reason, 'raw': 'PRIVATE_PAYLOAD'}
                    with self.assertRaises(trial.PhaseUnavailable) as caught:
                        if stage == 'begin-observer':
                            trial.begin('owned', 'cohort-a', {'source': 'b'*64}, Commands('cold'), unavailable)
                        else:
                            trial.finish(cold['begin'], 'cold', Commands('cold'), unavailable)
                    result = trial.failure_diagnostic(caught.exception)
                    expected = reason if isinstance(reason, str) and reason in trial.PHASE_REASONS else 'unsupported_schema'
                    self.assertEqual(result['phase'], {'app': jvm.APPS[0], 'stage': stage, 'reason': expected})
                    self.assertNotIn('PRIVATE', json.dumps(result))
        error = trial.PhaseUnavailable('PRIVATE_APP', 'PRIVATE_STAGE', 'PRIVATE_REASON')
        error.app = ['PRIVATE']; error.stage = {'PRIVATE': True}; error.reason = 'PRIVATE_REASON'
        self.assertEqual(trial.failure_diagnostic(error)['phase'],
                         {'app': None, 'stage': 'unknown', 'reason': 'unsupported_schema'})

    def test_failure_location_never_exports_exception_values_or_foreign_paths(self):
        try:
            trial.token('PRIVATE_TOKEN_SENTINEL /PRIVATE_PATH_SENTINEL')
        except trial.Invalid as error:
            diagnostic = trial.failure_diagnostic(error)
        self.assertEqual(diagnostic['kind'], 'guard-rejection')
        self.assertEqual(diagnostic['module'], 'startup_trials')
        self.assertGreater(diagnostic['line'], 0)
        self.assertEqual(diagnostic['source_sha256'], trial.hashlib.sha256(Path(trial.__file__).read_bytes()).hexdigest())
        try:
            trial.token('PRIVATE_TOKEN_SENTINEL/INVALID')
        except trial.Invalid as error:
            with patch.object(Path, 'read_bytes', side_effect=OSError('PRIVATE_IO_SENTINEL')):
                unavailable = trial.failure_diagnostic(error)
        self.assertEqual(unavailable['module'], 'startup_trials')
        self.assertIsNone(unavailable['source_sha256'])
        self.assertNotIn('PRIVATE', json.dumps(unavailable))
        for error in (KeyError('PRIVATE_KEY_SENTINEL'), RuntimeError('PRIVATE_RAW_SENTINEL')):
            value = trial.failure_diagnostic(error)
            self.assertEqual(value['module'], 'unavailable')
            self.assertEqual(value['line'], 0)
            self.assertNotIn('PRIVATE', json.dumps(value))

    def test_observer_guard_reports_reviewed_caller_and_only_fixed_reason(self):
        try:
            jvm.identity({}, 'takserver-api')
        except jvm.Unavailable as error:
            result=trial.failure_diagnostic(error)
        self.assertEqual(result['module'],'jvm_metrics')
        self.assertEqual(result['observer_reason'],'pod_namespace_or_deleted')
        self.assertIn("'pod_namespace_or_deleted'",Path(jvm.__file__).read_text().splitlines()[result['line']-1])
        self.assertNotIn('observer_reason',trial.failure_diagnostic(jvm.Unavailable('PRIVATE_SENTINEL')))
        self.assertNotIn('PRIVATE',json.dumps(trial.failure_diagnostic(jvm.Unavailable('PRIVATE_SENTINEL'))))

    def test_failed_command_diagnostic_does_not_export_raw_values(self):
        value=trial.failure_diagnostic(jvm.CommandFailure('secret','forbidden',1))
        self.assertEqual(value['command'],{'operation':'secret','category':'forbidden','exit_status':1})
        self.assertNotIn('PRIVATE',json.dumps(trial.failure_diagnostic(jvm.CommandFailure('PRIVATE','PRIVATE',True))))

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

    def test_optional_configmap_absence_is_bound_and_required_references_win(self):
        class OptionalCommands(Commands):
            def __init__(self,optional=True,present=False,denied=False):
                super().__init__('cold');self.optional=optional;self.present=present;self.denied=denied
            def run(self,args,limit):
                if args[:3]==['get','configmap','uds-trust-bundle']:
                    self.calls.append(args)
                    if self.denied:raise jvm.CommandFailure('configmap','forbidden',1)
                    if not self.present:
                        if '--ignore-not-found' not in args:raise jvm.CommandFailure('configmap','not-found',1)
                        return b''
                    return json.dumps({'metadata':{'uid':'trust-a','resourceVersion':'1'},'data':{'ca':'PRIVATE_TRUST_SENTINEL'}}).encode()
                raw=super().run(args,limit)
                if args[:2]==['get','deployments']:
                    value=json.loads(raw)
                    for deployment in value['items']:
                        deployment['spec']['template']['spec']['volumes'].append({'configMap':{'name':'uds-trust-bundle','optional':self.optional}})
                    return json.dumps(value).encode()
                return raw
        absent=OptionalCommands();missing,_=trial.snapshot(absent)
        self.assertTrue(any('--ignore-not-found' in argv for argv in absent.calls))
        present,_=trial.snapshot(OptionalCommands(present=True))
        self.assertNotEqual(missing['config_sha256'],present['config_sha256'])
        self.assertNotIn('PRIVATE_TRUST_SENTINEL',json.dumps(present))
        for kwargs in ({'optional':False},{'optional':'true'},{'denied':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(jvm.CommandFailure):trial.snapshot(OptionalCommands(**kwargs))
        refs=trial.references({'volumes':[{'configMap':{'name':'same','optional':True}},
                                         {'configMap':{'name':'same'}}]})
        self.assertNotIn('same',refs['optional_configmaps'])

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

    def test_every_reported_phase_and_sample_is_bound_to_this_collection(self):
        cold, warm = pair(); app = jvm.APPS[0]
        for name in ('container-elapsed', 'pull-elapsed', 'missing-container-elapsed', 'stale-samples', 'bad-pull-path'):
            with self.subTest(name=name):
                c, w = copy.deepcopy(cold), copy.deepcopy(warm); phase = w['phases'][app]
                if name == 'container-elapsed': phase['container_to_log_s'] = 999
                elif name == 'pull-elapsed': phase['image_pull_s'] = 999
                elif name == 'missing-container-elapsed': phase['container_to_log_s'] = None
                elif name == 'stale-samples': w['observed_started_at'] = '2024-01-01T00:00:28Z'
                else:
                    phase['evidence']['pull_events'] = [{'uid': 'pull-a', 'reason': 'Pulled', 'container': 'spec.containers{unknown}', 'at': '2024-01-01T00:00:20Z'}]
                with self.assertRaises(trial.Invalid): trial.validate_pair(c, w)

    def test_init_sidecar_images_and_actual_projected_pull_pairs_are_bound(self):
        class ExtraImages(Commands):
            def run(self, args, limit):
                raw = super().run(args, limit)
                if args[:2] == ['get', 'deployments']:
                    body = json.loads(raw)
                    for item in body['items']:
                        item['spec']['template']['spec']['containers'].append({'name': 'sidecar', 'image': 'example/sidecar:mutable'})
                        item['spec']['template']['spec']['initContainers'] = [{'name': 'setup', 'image': 'example/setup:mutable'}]
                    return json.dumps(body).encode()
                if args[:2] == ['get', 'pods']:
                    body = json.loads(raw)
                    for item in body['items']:
                        base = '20' if self.state == 'warm' else '00'
                        item['spec']['containers'].append({'name': 'sidecar', 'image': 'example/sidecar:mutable'})
                        item['spec']['initContainers'] = [{'name': 'setup', 'image': 'example/setup:mutable'}]
                        item['status']['containerStatuses'].append({'name': 'sidecar', 'imageID': 'sha256:'+'c'*64,
                            'state': {'running': {'startedAt': '2024-01-01T00:00:'+base+'.600Z'}}})
                        item['status']['initContainerStatuses'] = [{'name': 'setup', 'imageID': 'sha256:'+'d'*64,
                            'state': {'terminated': {'startedAt': '2024-01-01T00:00:'+base+'Z', 'finishedAt': '2024-01-01T00:00:'+base+'Z'}}}]
                    return json.dumps(body).encode()
                if args[:2] == ['get', 'events']:
                    uid = args[-3].split('=', 1)[1]; base = '20' if self.state == 'warm' else '00'
                    return json.dumps({'items': [{'metadata': {'uid': 'event-'+reason}, 'reason': reason,
                        'involvedObject': {'uid': uid, 'fieldPath': 'spec.containers{sidecar}'},
                        'eventTime': '2024-01-01T00:00:'+base+suffix+'Z'} for reason, suffix in [('Pulling', '.100'), ('Pulled', '.600')]]}).encode()
                return raw
        cold, warm = pair(ExtraImages); app = jvm.APPS[0]
        self.assertTrue(trial.validate_pair(cold, warm)['accepted'])
        self.assertEqual(warm['phases'][app]['image_pull_s'], .5)
        for name in ('sidecar', 'setup'):
            with self.subTest(name=name):
                changed = copy.deepcopy(warm)
                next(item for item in changed['snapshot']['container_images'][app] if item['name'] == name)['image_id'] = 'sha256:'+'e'*64
                with self.assertRaises(trial.Invalid): trial.validate_pair(cold, changed)
        for mutation in ('duration', 'duplicate', 'late', 'missing-uid'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(warm); phase = changed['phases'][app]
                if mutation == 'duration': phase['image_pull_s'] = 999
                elif mutation == 'duplicate': phase['evidence']['pull_events'].append(copy.deepcopy(phase['evidence']['pull_events'][0]))
                elif mutation == 'late': phase['evidence']['pull_events'][1]['at'] = '2024-01-01T00:00:27Z'
                else: phase['evidence']['pull_events'][0]['uid'] = None
                with self.assertRaises(trial.Invalid): trial.validate_pair(cold, changed)
        p = application(app)
        p['spec']['containers'].append(copy.deepcopy(p['spec']['containers'][0]))
        with self.assertRaises(trial.Invalid): trial.container_images(p)
        p = application(app); p['status']['containerStatuses'].append({'name': 'unexpected', 'imageID': 'sha256:'+'e'*64})
        with self.assertRaises(trial.Invalid): trial.container_images(p)

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
            with self.subTest(kind=kind), patch.object(trial, 'stamp', side_effect=['2024-01-01T00:00:26.500Z', '2024-01-01T00:00:30Z']):
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


class StartupWorkflow(unittest.TestCase):
    def setUp(self):
        self.document = yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/startup.yaml').read_text())
        self.job = self.document['jobs']['startup']
        self.steps = self.job['steps']

    def test_only_manual_main_and_selected_bounded_read_only_runners_can_run(self):
        self.assertEqual(set(self.document.get('on', self.document.get(True))), {'workflow_dispatch'})
        dispatch = self.document.get('on', self.document.get(True))['workflow_dispatch']
        self.assertEqual(dispatch['inputs']['architecture']['default'], 'amd64')
        self.assertEqual(dispatch['inputs']['architecture']['options'], ['amd64', 'arm64', 'both'])
        self.assertEqual(set(self.document['jobs']), {'plan', 'startup'})
        self.assertEqual(self.job['if'], "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'")
        self.assertEqual(self.document['jobs']['plan']['if'], self.job['if'])
        self.assertEqual(self.job['needs'], 'plan')
        self.assertFalse(self.job['strategy']['fail-fast'])
        self.assertEqual(self.job['runs-on'], '${{ matrix.runner }}')
        self.assertLessEqual(self.job['timeout-minutes'], 60)
        self.assertFalse(self.document['concurrency']['cancel-in-progress'])
        self.assertTrue(all(level == 'read' for level in self.document['permissions'].values()))
        self.assertNotIn('permissions', self.job)
        self.assertFalse(any(step.get('continue-on-error') for step in self.steps))

    def test_actual_planner_selects_native_rows_and_rejects_unknown_inputs(self):
        script = self.document['jobs']['plan']['steps'][0]['run']
        for selected, runner, expected in [('amd64', 'ubuntu-24.04', {'amd64'}),
                ('arm64', 'ubuntu-22.04', {'arm64'}), ('both', 'ubuntu-22.04', {'amd64', 'arm64'}),
                ('arm64', 'PRIVATE\nunused-runner', {'arm64'}),
                ('PRIVATE_SELECTION', 'ubuntu-22.04', None), ('both', 'PRIVATE\nrunner', None)]:
            with self.subTest(selected=selected, runner=runner), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)/'output'; output.touch()
                result = subprocess.run(['bash', '-e', '-c', script], capture_output=True, text=True,
                    env={**os.environ, 'ARCHITECTURE': selected, 'AMD64_RUNNER': runner, 'GITHUB_OUTPUT': str(output)})
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.read_text(), '')
                    self.assertNotIn('PRIVATE', result.stdout+result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    rows = json.loads(output.read_text().removeprefix('matrix='))['include']
                    self.assertEqual({row['arch'] for row in rows}, expected)
                    self.assertEqual(len(rows), len(expected))
                    for row in rows:
                        self.assertEqual(row['runner'], 'ubuntu-22.04-arm' if row['arch']=='arm64' else runner)

    def test_actual_native_machine_guard_rejects_cross_arch_and_unknown_runners(self):
        step = next(step for step in self.steps if step['name']=='Verify native architecture before setup or cluster work')
        with tempfile.TemporaryDirectory() as directory:
            uname = Path(directory)/'uname'
            uname.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_MACHINE"\n'); uname.chmod(0o700)
            for arch, machine, accepted in [('amd64', 'x86_64', True), ('arm64', 'aarch64', True),
                    ('amd64', 'aarch64', False), ('arm64', 'x86_64', False),
                    ('arm64', 'PRIVATE_MACHINE', False), ('PRIVATE_ARCH', 'x86_64', False)]:
                with self.subTest(arch=arch, machine=machine):
                    result = subprocess.run(['bash', '-c', step['run']], capture_output=True, text=True,
                        env={**os.environ, 'PATH': directory+os.pathsep+os.environ['PATH'],
                             'STARTUP_ARCH': arch, 'TEST_MACHINE': machine})
                    self.assertEqual(result.returncode==0, accepted)
                    self.assertNotIn('PRIVATE', result.stdout+result.stderr)

    def test_fresh_cluster_and_published_input_guards_precede_deployment(self):
        scripts = [step.get('run', '') for step in self.steps]
        index = lambda needle: next(i for i, script in enumerate(scripts) if needle in script)
        self.assertLess(index('ephemeral-cluster.py bootstrap'), index('trim-runner.sh'))
        self.assertLess(index('dev-package.sh prebuilt'), index('uds run deploy-slim-core'))
        self.assertLess(index('uds run deploy-slim-core'), index('startup_trials begin'))
        self.assertLess(index('startup_trials begin'), index('uds run create-deploy-test-bundle'))
        joined = '\n'.join(scripts)
        for forbidden in ('bench/run.py', 'tak_tester', 'create-dev-package', 'test-install', 'JAVA_OPTIONS', 'probe-tuning', 'wait-for-tak-images.sh'):
            self.assertNotIn(forbidden, joined)
        self.assertLess(index('Startup runner architecture mismatch'), index('ephemeral-cluster.py bootstrap'))
        self.assertIn('test "$(./.github/scripts/dev-package.sh prebuilt)" = true', joined)

    def test_warm_rollout_occurs_between_boundaries_and_pair_validation(self):
        joined = '\n'.join(step.get('run', '') for step in self.steps)
        needles = ['--mode cold', '--output "$EVIDENCE/warm-begin.json"', 'ephemeral-cluster.py verify',
                   'rollout restart deployment/takserver-api deployment/takserver-messaging', '--mode warm', 'startup_trials pair']
        positions = [joined.index(needle) for needle in needles]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(joined.count('rollout restart'), 1)
        self.assertIn("'--for=delete', *names, '--timeout=60s'", joined)
        self.assertIn("value['snapshot']['identities'][app]['pod_name']", joined)
        self.assertIn('sha = os.environ[\'GITHUB_SHA\']', joined)
        self.assertIn("'source': hashlib.sha256(sha.encode()).hexdigest()", joined)

    def test_artifact_retains_only_typed_records_even_after_failure(self):
        uploads = [step for step in self.steps if step.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads), 1)
        self.assertIn('${{ matrix.arch }}', uploads[0]['with']['name'])
        self.assertIn('${{ matrix.arch }}', self.job['env']['COHORT'])
        self.assertEqual(uploads[0]['if'], "always() && steps.checkout.outcome == 'success'")
        paths = uploads[0]['with']['path'].splitlines()
        self.assertEqual({Path(path).name for path in paths}, {'bindings.json', 'cold-begin.json', 'cold.json', 'warm-begin.json', 'warm.json', 'pair.json'})
        self.assertTrue(all(path.startswith('${{ runner.temp }}/startup-pair/') and '*' not in path for path in paths))
        self.assertLessEqual(uploads[0]['with']['retention-days'], 14)
