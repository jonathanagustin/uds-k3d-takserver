# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Numeric/identity/protocol fixtures; no Kubernetes or application JVM calls."""
import copy
import contextlib
import io
import json
import os
import re
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import yaml

from bench import jvm_metrics as jvm
from bench import run, phases

APP = 'takserver-api'
UID = '12345678-1234-1234-1234-123456789abc'
CID = 'containerd://' + 'a'*64
IMAGE = 'ghcr.io/example/api@sha256:'+'b'*64
START = 1704067201000


def metrics(start='1.704067201E9', total='20', current='18', unloaded='2'):
    return (f'process_start_time_seconds {start}\njvm_classes_currently_loaded {current}\n'
            f'jvm_classes_loaded_total {total}\njvm_classes_unloaded_total {unloaded}\n').encode()


def pod():
    return {'metadata': {'name': APP+'-abc', 'namespace': 'takserver', 'uid': UID},
            'spec': {'containers': [{'name': 'sidecar'}, {'name': APP}]},
            'status': {'containerStatuses': [{'name': 'sidecar'}, {'name': APP, 'containerID': CID,
              'imageID': IMAGE, 'restartCount': 0, 'state': {'running': {'startedAt': '2024-01-01T00:00:00Z'}}}],
              'conditions': [{'type': 'Ready', 'status': 'True', 'lastTransitionTime': '2024-01-01T00:00:06Z'}]}}


def fake_commands(first=None, last=None, bodies=None):
    first = first or pod()
    last = last or copy.deepcopy(first)
    commands = Mock()
    commands.pod.side_effect = [{'items': [first]}, last]
    commands.run.side_effect = bodies or [metrics(), metrics(total='21', current='17', unloaded='4')]
    return commands


class MetricsTests(unittest.TestCase):
    def test_numeric_allowlist_excludes_unrelated_payload_and_preserves_epoch_ms(self):
        value = jvm.parse_metrics(metrics()+b'# secret comment\nunknown{secret="SENTINEL"} 42\n')
        self.assertEqual(value['jvm_start_time_unix_ms'], START)
        self.assertEqual(value['jvm_classes_loaded_total'], 20)
        self.assertNotIn('SENTINEL', json.dumps(value))
        self.assertEqual(jvm.parse_metrics(metrics(start='1704067201.0000002'))['jvm_start_time_unix_ms'], START)

    def test_missing_duplicate_labels_partial_and_invalid_numbers_fail_closed(self):
        values = [metrics().splitlines()[0], metrics()+metrics(), metrics().replace(b'process_start_time_seconds ', b'process_start_time_seconds{secret="SENTINEL"} '),
                  metrics(total='1.5'), metrics(total='NaN'), metrics(total='-1'), metrics(start='Infinity'),
                  metrics(start='0'), metrics()+b'jvm_classes_loaded_total 3 1234\n', b'x'*(jvm.MAX_METRICS+1)]
        for value in values:
            with self.subTest(value=value[:50]), self.assertRaises(jvm.Unavailable) as caught:
                jvm.parse_metrics(value)
            self.assertNotIn('SENTINEL', str(caught.exception))

    def test_snapshot_named_container_stable_identity_and_proxy_only(self):
        commands = fake_commands()
        value = jvm.observe(APP, 'k3d-uds', commands)
        self.assertTrue(value['available'], value)
        self.assertEqual(value['identity']['container_id'], CID)
        self.assertEqual(value['identity']['image_id'], 'sha256:'+'b'*64)
        self.assertEqual(value['observation_kind'], 'existing-incarnation-snapshot')
        for call in commands.run.call_args_list:
            self.assertEqual(call.args, (['get', '--raw', '/api/v1/namespaces/takserver/pods/'+APP+'-abc:9100/proxy/metrics'], 65536))
        self.assertNotIn('class_loading_duration', value)

    def test_every_identity_boundary_and_jvm_or_total_reset_is_rejected(self):
        for field, replacement in [('containerID', 'containerd://'+'c'*64), ('imageID', 'sha256:'+'c'*64), ('restartCount', 1)]:
            final = pod(); final['status']['containerStatuses'][1][field] = replacement
            self.assertEqual(jvm.observe(APP, 'k3d-uds', fake_commands(last=final))['reason'], 'pod_incarnation_changed')
        for field, replacement in [('uid', 'a'*8+'-1234-1234-1234-123456789abc'), ('deletionTimestamp', '2024-01-01T00:00:04Z')]:
            final = pod(); final['metadata'][field] = replacement
            self.assertFalse(jvm.observe(APP, 'k3d-uds', fake_commands(last=final))['available'])
        for final_body, reason in [(metrics(start='1704067202'), 'jvm_incarnation_changed'), (metrics(total='19'), 'class_counter_reset')]:
            value = jvm.observe(APP, 'k3d-uds', fake_commands(bodies=[metrics(), final_body]))
            self.assertEqual(value['reason'], reason)
        bad = pod();bad['status']['containerStatuses'][1]['state']['running']['startedAt'] = '2024-01-01T00:00:03Z'
        self.assertEqual(jvm.observe(APP, 'k3d-uds', fake_commands(first=bad))['reason'], 'jvm_start_outside_lifetime')

    def test_ambiguity_context_and_payload_errors_do_not_escape(self):
        commands = fake_commands();commands.pod.side_effect = [{'items':[pod(),pod()]}]
        self.assertEqual(jvm.observe(APP, 'k3d-uds', commands)['reason'], 'pod_ambiguous')
        value = jvm.observe(APP, 'secret://SENTINEL', fake_commands())
        self.assertEqual(value['reason'], 'context_required')
        self.assertNotIn('SENTINEL', json.dumps(value))
        bad = pod();bad['status']['containerStatuses'][1]['imageID']='https://SENTINEL/path@sha256:'+'b'*64
        value = jvm.observe(APP, 'k3d-uds', fake_commands(first=bad))
        self.assertEqual(value['reason'], 'image_id')
        self.assertNotIn('SENTINEL', json.dumps(value))

    def test_phase_join_requires_exact_identity_and_clears_previous_evidence(self):
        phase = phases.pod_phases(pod(), [], '2024-01-01T00:00:05Z Started TAK Server', container_name=APP)
        value = jvm.observe(APP, 'k3d-uds', fake_commands())
        jvm.join_phase(phase, value)
        self.assertEqual(phase['jvm_to_log_s'], 4)
        self.assertEqual(phase['evidence']['jvm_started_at'], '2024-01-01T00:00:01+00:00')
        value['identity']['image_id'] = 'sha256:'+'c'*64
        jvm.join_phase(phase, value)
        self.assertIsNone(phase['jvm_to_log_s'])
        self.assertIsNone(phase['evidence']['jvm_started_at'])
        self.assertEqual(phase['jvm_observation']['reason'], 'phase_identity_mismatch')
        for marker in (None, '2024-01-01T00:00:00Z'):
            phase = phases.pod_phases(pod(), [], '', container_name=APP)
            phase['evidence']['startup_log_at'] = marker
            self.assertIsNone(jvm.join_phase(phase, jvm.observe(APP, 'k3d-uds', fake_commands()))['jvm_to_log_s'])

    def test_rejected_marker_timing_retains_independent_bound_metrics(self):
        observation = jvm.observe(APP, 'k3d-uds', fake_commands())
        for marker in ('2024-01-01T00:00:06.059396Z',
                       '2024-01-01T00:00:07Z'):
            with self.subTest(marker=marker):
                phase = phases.pod_phases(pod(), [], marker + ' Started TAK Server', container_name=APP)
                jvm.join_phase(phase, observation)
                self.assertIsNone(phase['jvm_to_log_s'])
                self.assertIsNone(phase['evidence']['jvm_started_at'])
                self.assertIsNone(phase['log_to_ready_s'])
                self.assertEqual(phase['jvm_observation'], {'available': False, 'reason': 'marker_after_ready'})
                retained = phase['jvm_metric_observation']
                self.assertEqual(retained, observation)
                self.assertEqual(retained['jvm_start_time_unix_ms'], START)
                self.assertEqual(len(retained['samples']), 2)
                self.assertIsNot(retained, observation)
                self.assertIsNot(retained['identity'], observation['identity'])

    def test_metrics_retention_requires_phase_identity_and_clears_stale_evidence(self):
        observation = jvm.observe(APP, 'k3d-uds', fake_commands())
        for key, value in [('pod_uid', 'different'), ('container_id', 'different'),
                           ('restart_count', 1), ('container_started_at', '2024-01-01T00:00:01Z')]:
            with self.subTest(key=key):
                phase = phases.pod_phases(pod(), [], '2024-01-01T00:00:05Z Started TAK Server', container_name=APP)
                jvm.join_phase(phase, observation)
                self.assertIn('jvm_metric_observation', phase)
                phase['evidence'][key] = value
                jvm.join_phase(phase, observation)
                self.assertNotIn('jvm_metric_observation', phase)
                self.assertEqual(phase['jvm_observation']['reason'], 'phase_identity_mismatch')
                self.assertIsNone(phase['jvm_to_log_s'])
        phase = phases.pod_phases(pod(), [], '', container_name=APP)
        jvm.join_phase(phase, observation)
        self.assertEqual(phase['jvm_metric_observation'], observation)
        self.assertIsNone(phase['jvm_to_log_s'])
        jvm.join_phase(phase, {'available': False, 'reason': 'deadline'})
        self.assertNotIn('jvm_metric_observation', phase)

    def test_numeric_start_format_is_not_a_false_incarnation_change(self):
        value = jvm.observe(APP, 'k3d-uds', fake_commands(bodies=[metrics(start='1704067201'), metrics(start='1.704067201E9')]))
        self.assertTrue(value['available'], value)

    def test_caller_provenance_is_curated_not_free_environment(self):
        with patch.dict(os.environ, {'GITHUB_SHA':'c'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','SECRET_URL':'SENTINEL'}):
            value = jvm.observe(APP, 'k3d-uds', fake_commands())
        self.assertEqual(value['caller'], {'source_sha':'c'*40,'run_id':'123','run_attempt':'2'})
        self.assertNotIn('SENTINEL', json.dumps(value))

    def test_default_phase_collector_never_calls_numeric_observer(self):
        with patch.dict(os.environ, {'BENCH_JVM_START_METADATA':'0'}), patch.object(run, 'kubectl', return_value=Mock(stdout='{"items":[]}')), patch.object(run.jvm_metrics, 'observe') as observe:
            run.start_phases()
        observe.assert_not_called()

    def test_opt_in_collector_selects_app_and_joins_existing_phase(self):
        item = pod()
        def kube(*args, **kwargs):
            self.assertEqual(args[:2], ('--context', 'k3d-uds'))
            if 'pods' in args: return Mock(stdout=json.dumps({'items':[item]}))
            if 'events' in args: return Mock(stdout='{"items":[]}')
            return Mock(stdout='2024-01-01T00:00:05Z Started TAK Server')
        observed = jvm.observe(APP, 'k3d-uds', fake_commands())
        with patch.dict(os.environ, {'BENCH_JVM_START_METADATA':'1', 'BENCH_JVM_CONTEXT':'k3d-uds'}), patch.object(run, 'kubectl', side_effect=kube), patch.object(run, 'redacted_text', side_effect=lambda s:s), patch.object(run.jvm_metrics, 'observe', return_value=observed), patch.object(run.jvm_metrics, 'current_context_matches', return_value=True):
            found, errors = run.start_phases()
        self.assertEqual(errors, [])
        self.assertEqual(found[APP]['jvm_to_log_s'], 4)
        self.assertEqual(found[APP]['evidence']['container_name'], APP)

    def test_differing_current_context_prevents_all_benchmark_phase_reads(self):
        with patch.dict(os.environ, {'BENCH_JVM_START_METADATA':'1', 'BENCH_JVM_CONTEXT':'k3d-uds'}), patch.object(jvm.Commands, 'run', return_value=b'other-cluster\n') as command, patch.object(run, 'kubectl') as kube, patch.object(jvm, 'observe') as observe:
            found, errors = run.start_phases()
        kube.assert_not_called()
        observe.assert_not_called()
        self.assertEqual(command.call_args.args, (['config', 'current-context'], 256))
        self.assertFalse(command.call_args.kwargs['use_context'])
        self.assertIn('benchmark_context_mismatch', errors[0])
        self.assertIsNone(found[APP]['jvm_to_log_s'])

    def test_optional_phase_error_does_not_echo_command_payload(self):
        with patch.dict(os.environ, {'BENCH_JVM_START_METADATA':'1', 'BENCH_JVM_CONTEXT':'k3d-uds'}), patch.object(jvm, 'current_context_matches', return_value=True), patch.object(run, 'kubectl', side_effect=RuntimeError('https://SENTINEL/password')):
            found, errors = run.start_phases()
        self.assertNotIn('SENTINEL', json.dumps([found,errors]))

    def test_ambiguous_phase_never_selects_first_pod_or_reads_its_logs(self):
        with patch.dict(os.environ, {'BENCH_JVM_START_METADATA':'1', 'BENCH_JVM_CONTEXT':'k3d-uds'}), patch.object(jvm, 'current_context_matches', return_value=True), patch.object(run, 'kubectl', return_value=Mock(stdout=json.dumps({'items':[pod(),pod()]}))) as kube, patch.object(jvm, 'observe') as observe:
            found, errors = run.start_phases()
        observe.assert_not_called()
        self.assertEqual(len(kube.call_args_list), 2)
        self.assertTrue(all('pods' in call.args for call in kube.call_args_list))
        self.assertEqual(found[APP]['jvm_observation']['reason'], 'phase_pod_ambiguous')
        self.assertIsNone(found[APP]['jvm_to_log_s'])


class CommandBoundsTests(unittest.TestCase):
    def command(self, code, seconds=1):
        return jvm.Commands('k3d-uds', time.monotonic()+seconds, [sys.executable, '-c', code])

    @contextlib.contextmanager
    def prepared(self, code, seconds=2, setup=''):
        # Start the real fixture interpreter before starting the collector's
        # deadline. This tests pipe/cleanup behavior rather than CI spawn lag.
        with tempfile.TemporaryDirectory() as directory:
            ready, go = Path(directory)/'ready', Path(directory)/'go'
            source = ("import os,signal,sys,time\nfrom pathlib import Path\n"+setup+"\n"
                      +"Path("+repr(str(ready))+").touch()\n"
                      +"while not Path("+repr(str(go))+").exists(): time.sleep(0.001)\n"+code)
            child = subprocess.Popen([sys.executable, '-c', source], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic()+20
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() >= deadline:
                        self.fail('fixture interpreter did not become ready')
                    time.sleep(0.01)
                command = self.command('unused', seconds)
                def launch(*args, **kwargs):
                    go.touch()
                    return child
                with patch.object(jvm.subprocess, 'Popen', side_effect=launch):
                    yield command
            finally:
                try: os.killpg(child.pid, 9)
                except ProcessLookupError: pass
                child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()

    def test_failed_command_emits_only_fixed_operation_category_and_status(self):
        code="sys.stdout.write('PRIVATE_STDOUT');sys.stderr.write('x'*20000+'Error from server (NotFound): PRIVATE_NAME PRIVATE_URL');sys.exit(7)"
        with self.prepared(code) as command:
            with self.assertRaises(jvm.CommandFailure) as caught:
                command.run(['get','configmap','PRIVATE_NAME'],65536)
        self.assertEqual(str(caught.exception),'command_failed')
        self.assertEqual(caught.exception.diagnostic(),{'operation':'configmap','category':'not-found','exit_status':7})
        self.assertNotIn('PRIVATE',json.dumps(caught.exception.diagnostic()))
        bad=jvm.CommandFailure('PRIVATE_OPERATION','PRIVATE_CATEGORY',True)
        self.assertEqual(bad.diagnostic(),{'operation':'other','category':'unknown','exit_status':None})
        bad.operation=[];bad.category={};bad.status='PRIVATE'
        self.assertEqual(bad.diagnostic(),{'operation':'other','category':'unknown','exit_status':None})

    def test_complete_stream_size_limit_and_raw_stderr_suppression(self):
        with self.prepared("sys.stdout.write('x'*65537);sys.stderr.write('SENTINEL')") as command:
            with self.assertRaises(jvm.Unavailable) as caught:
                command.run([], 65536)
        self.assertNotIn('SENTINEL', str(caught.exception))
        with self.prepared("print('123')") as command:
            self.assertEqual(command.run([], 64), b'123\n')
        with self.assertRaisesRegex(jvm.Unavailable, 'deadline'):
            self.command('pass', seconds=-1).run([], 64)

    def test_stdout_cap_does_not_restrict_legitimate_child_file_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'discovery-cache'
            code = "from pathlib import Path; Path("+repr(str(path))+").write_bytes(b'x'*100000); print('ok')"
            with self.prepared(code) as command:
                self.assertEqual(command.run([], 64), b'ok\n')
            self.assertEqual(path.stat().st_size, 100000)

    def test_context_request_timeout_and_duplicate_json_contract(self):
        command = self.command('pass')
        with patch.object(command, 'run', return_value=b'{"items":[],"items":[]}'):
            with self.assertRaisesRegex(jvm.Unavailable, 'pod_duplicate_field'):
                command.pod(['pods'])
        with patch.object(jvm.subprocess, 'Popen', side_effect=OSError('SENTINEL')) as launch:
            with self.assertRaisesRegex(jvm.Unavailable, '^command_unavailable$'):
                command.run(['get', 'pods'], 64)
            args = launch.call_args.args[0]
            self.assertIn('--context', args)
            self.assertIn('k3d-uds', args)
            self.assertIn('--request-timeout=2s', args)

    def test_reused_command_budget_is_total_not_renewed_per_read(self):
        with self.prepared("print('ok')", seconds=0.5) as command:
            self.assertEqual(command.run([], 64), b'ok\n')
            time.sleep(0.6)
            with self.assertRaisesRegex(jvm.Unavailable, 'deadline'):
                command.run([], 64)

    def test_cli_argument_failure_does_not_echo_freeform_input(self):
        result = subprocess.run([sys.executable, '-m', 'bench.jvm_metrics', '--context', 'k3d-uds', '--app', 'https://SENTINEL/password'], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('SENTINEL', result.stdout+result.stderr)

    def test_timeout_kills_sigterm_ignoring_descendant_and_reaps_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory)/'pid'
            setup = ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\npid=os.fork()\n"
                     "Path("+repr(str(pidfile))+").write_text(str(os.getpid())) if pid==0 else None\n"
                     "while not Path("+repr(str(pidfile))+").exists(): time.sleep(0.001)")
            with self.prepared('time.sleep(30)', seconds=0.5, setup=setup) as command:
                started = time.monotonic()
                with self.assertRaises(jvm.Unavailable):
                    command.run([], 64)
                self.assertLess(time.monotonic()-started, 3)
            pid = int(pidfile.read_text())
            for _ in range(50):
                try: state = (Path('/proc')/str(pid)/'stat').read_text().split()[2]
                except (FileNotFoundError, ProcessLookupError): break
                if state == 'Z': break
                time.sleep(0.01)
            else:
                os.kill(pid, 9)
                self.fail('descendant survived owned session cleanup')


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((run.ROOT / '.github/workflows/benchmark.yaml').read_text())
        self.events = self.workflow.get('on', self.workflow.get(True))

    def selected(self, key, event, requested=None):
        # Evaluate only the actual workflow's small typed boolean expression;
        # unknown fields/operators fail rather than silently assuming a guard.
        expression = self.workflow['jobs']['benchmark']['env'][key]
        match = re.fullmatch(r"\$\{\{ (.+) && '([^']*)' \|\| '([^']*)' \}\}", expression)
        self.assertIsNotNone(match)
        values = {'github.event_name': event, 'inputs.jvm_start_metadata': requested}
        enabled = True
        seen = set()
        for term in match[1].split(' && '):
            condition = re.fullmatch(r"(github\.event_name|inputs\.jvm_start_metadata) == ('workflow_dispatch'|true)", term)
            self.assertIsNotNone(condition)
            expected = True if condition[2] == 'true' else 'workflow_dispatch'
            value = values[condition[1]]
            enabled = enabled and type(value) is type(expected) and value == expected
            seen.add(condition[1])
        self.assertEqual(seen, set(values))
        return match[2] if enabled else match[3]

    def test_typed_manual_input_defaults_off_without_freeform_context(self):
        inputs = self.events['workflow_dispatch']['inputs']
        self.assertEqual(inputs['jvm_start_metadata']['type'], 'boolean')
        self.assertIs(inputs['jvm_start_metadata']['default'], False)
        self.assertNotIn('jvm_context', inputs)
        self.assertEqual(self.selected('BENCH_JVM_START_METADATA', 'workflow_dispatch'), '0')
        self.assertEqual(self.selected('BENCH_JVM_CONTEXT', 'workflow_dispatch'), '')

    def test_only_explicit_manual_true_enables_fixed_context(self):
        self.assertEqual(self.selected('BENCH_JVM_START_METADATA', 'workflow_dispatch', True), '1')
        self.assertEqual(self.selected('BENCH_JVM_CONTEXT', 'workflow_dispatch', True), 'k3d-uds')
        self.assertEqual(self.selected('BENCH_JVM_START_METADATA', 'workflow_dispatch', False), '0')
        self.assertEqual(self.selected('BENCH_JVM_CONTEXT', 'workflow_dispatch', False), '')

    def test_pr_schedule_and_other_events_cannot_enable_even_with_true_input(self):
        for event in ('pull_request', 'schedule', 'push', 'workflow_call'):
            for requested in (None, False, True):
                with self.subTest(event=event, requested=requested):
                    self.assertEqual(self.selected('BENCH_JVM_START_METADATA', event, requested), '0')
                    self.assertEqual(self.selected('BENCH_JVM_CONTEXT', event, requested), '')

    def test_sweep_receives_metadata_only_through_existing_environment(self):
        job = self.workflow['jobs']['benchmark']
        self.assertEqual(len(job['strategy']['matrix']['include']), 2)
        sweep = next(step for step in job['steps'] if step.get('name') == 'Run the sweep')
        self.assertNotIn('BENCH_JVM_START_METADATA', sweep.get('env', {}))
        self.assertNotIn('BENCH_JVM_CONTEXT', sweep.get('env', {}))
        self.assertIn('bench/run.py', sweep['run'])


if __name__ == '__main__':
    unittest.main()
