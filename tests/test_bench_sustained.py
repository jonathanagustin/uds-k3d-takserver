# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic protocol fixtures; no actual clients, cluster or traffic."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from bench import sustained, tester_exit, report
from tests.test_bench import runner


class SustainedTests(unittest.TestCase):
    def window(self):
        return {'ready': {str(i): [0, 0, 1, 0, 0, 0, 0] for i in range(50)},
                'ready_monotonic': 0, 'ready_unix': 700, 'before': {str(i): [100, 200, 1, 0, 50, 50, 500] for i in range(50)},
                'after': {str(i): [580, 12200, 1, 0, 290, 290, 2900] for i in range(50)},
                'start_monotonic': 300, 'end_monotonic': 1500.5,
                'start_unix': 1000, 'end_unix': 2200.5}

    def parse(self, value):
        return sustained.parse_window('warmup ignored\nBENCH_WINDOW_JSON:' + json.dumps(value))

    def test_delta_excludes_warmup_and_rates_keep_fanout_semantics(self):
        result = self.parse(self.window())
        self.assertEqual(result['messages_sent'], 24000)
        self.assertEqual(result['messages_received'], 600000)
        self.assertEqual(result['observed_stable_clients'], 50)
        self.assertEqual(result['offered_self_sa_per_s'], 10)
        self.assertEqual(result['ping_pong_ms_mean'], 10)
        self.assertAlmostEqual(result['received_messages_per_s'], 600000/1200.5)

    def test_missing_reset_connection_and_short_window_reject(self):
        variants = []
        for change in ('missing', 'reconnect', 'disconnect', 'reset', 'short', 'zero', 'warmup-short', 'warmup-reconnect', 'object'):
            value = self.window()
            if change == 'missing':
                value['before'].pop('0')
            elif change == 'reconnect':
                value['after']['0'][2:4] = [2, 1]
            elif change == 'disconnect':
                value['after']['0'][3] = 1
            elif change == 'reset':
                value['after']['0'][0] = 1
            elif change == 'short':
                value['end_monotonic'] = 400
            elif change == 'warmup-short':
                value['ready_monotonic'] = 1
            elif change == 'warmup-reconnect':
                value['ready']['0'][2:4] = [0, 0]
            elif change == 'zero':
                for row in value['after'].values():
                    row[:] = [100, 200, 1, 0, 50, 50, 500]
            else:
                value['before'] = None
            variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)
        with self.assertRaises(ValueError):
            sustained.parse_window('')

    def test_frozen_clients_retain_invalid_raw_window(self):
        value = self.window()
        for uid in list(value['after'])[1:]:
            value['after'][uid] = list(value['before'][uid])
        with self.assertRaises(sustained.WindowInvalid) as caught:
            self.parse(value)
        self.assertEqual(caught.exception.window, value)

    def test_parent_tracks_only_actual_cot_children_and_refuses_exit(self):
        source = (runner.ROOT / 'bench/fixtures/tester/tak_tester.py.txt').read_text()
        bound = sustained.bind(tester_exit.bind_tester(source), tester_exit.ANCHOR)
        self.assertEqual(bound.count('_bench_clients[uid] = p'), 1)
        namespace = {'time': Mock()}
        exec(tester_exit.HELPER + sustained.HELPER, namespace)
        child = SimpleNamespace(is_alive=lambda: True, exitcode=None)
        namespace['_bench_clients'] = {'client': child}
        self.assertTrue(namespace['_bench_check_clients']())
        child.exitcode = 1
        self.assertFalse(namespace['_bench_check_clients']())
        self.assertTrue(namespace['_tak_tester_should_stop']())

    def test_db_delta_preserves_raw_settings_and_detects_reset(self):
        first = {key: 100 for key in sustained.DB_COUNTERS}
        first.update(settings={'shared_buffers': '128MB'}, peak_rss_bytes=None, stats_reset={k: None for k in ('stats_reset_database', 'stats_reset_checkpointer', 'stats_reset_io')})
        last = {key: 102 for key in sustained.DB_COUNTERS}
        last.update(settings={'shared_buffers': '128MB'}, peak_rss_bytes=123, stats_reset=first['stats_reset'])
        result = sustained.postgres_delta(first, last)
        self.assertEqual(result['checkpoints_timed'], 2)
        self.assertEqual(result['checkpoint_write_ms'], 2)
        self.assertEqual(result['window_before'], first)
        self.assertEqual(result['peak_rss_bytes'], 123)
        reset = copy.deepcopy(last)
        reset['stats_reset']['stats_reset_io'] = 'changed'
        with self.assertRaises(ValueError):
            sustained.postgres_delta(first, reset)
        last['checkpoints_req'] = 0
        with self.assertRaises(ValueError):
            sustained.postgres_delta(first, last)

    def test_mode_rejects_tuning_and_old_defaults_stay_short(self):
        self.assertFalse(sustained.enabled({}))
        self.assertTrue(sustained.enabled({'BENCH_STUDY': 'synthetic-baseline', 'BENCH_PROFILE': 'baseline', 'BENCH_CLIENTS': '50'}))
        for changes in ({'BENCH_PROFILE': 'all'}, {'BENCH_CLIENTS': '200'}, {'BENCH_STUDY': 'unknown'}):
            env = {'BENCH_STUDY': 'synthetic-baseline', 'BENCH_PROFILE': 'baseline', 'BENCH_CLIENTS': '50', **changes}
            with self.assertRaises(ValueError):
                sustained.enabled(env)

    def test_real_pinned_tester_rewrite_and_parent_boundary(self):
        source = (runner.ROOT / 'bench/fixtures/tester/tak_tester.py.txt').read_text()
        bound = sustained.bind(tester_exit.bind_tester(source), tester_exit.ANCHOR)
        compile(bound, 'fixture', 'exec')
        clock = Mock()
        clock.monotonic.return_value = 300
        clock.time.return_value = 1000
        namespace = {'time': clock}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'BENCH_WINDOW_READY': directory+'/ready', 'BENCH_WINDOW_GO': directory+'/go', 'BENCH_WINDOW_START': directory+'/start', 'BENCH_WINDOW_END': directory+'/end'}):
            exec(tester_exit.HELPER + sustained.HELPER, namespace)
            namespace['_bench_clients'] = {str(i): SimpleNamespace(is_alive=lambda: True, exitcode=None) for i in range(50)}
            namespace['_bench_snapshot'] = Mock(side_effect=[self.window()['ready'], self.window()['before'], self.window()['after']])
            self.assertFalse(namespace['_tak_tester_should_stop']())
            Path(directory, 'go').touch()
            clock.monotonic.return_value = 600
            self.assertFalse(namespace['_tak_tester_should_stop']())
            clock.monotonic.return_value = 1800
            clock.time.return_value = 2200
            self.assertTrue(namespace['_tak_tester_should_stop']())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                namespace['_tak_tester_emit_stats']()
                namespace['_tak_tester_emit_stats']()
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            self.assertEqual(sustained.parse_window(output.getvalue())['messages_sent'], 24000)
            self.assertTrue(Path(directory, 'end').exists())

    def test_snapshot_carries_per_uid_monotonic_read_times(self):
        class Array(list):
            def get_lock(self):
                return lock
        lock = Mock()
        lock.acquire.return_value = True
        clock = Mock()
        clock.monotonic.return_value = 10
        namespace = {'time': clock, 'stats': SimpleNamespace(data={'uid': Array([1,2,1,0,1,1,4])})}
        exec(tester_exit.HELPER + sustained.HELPER, namespace)
        self.assertEqual(namespace['_bench_snapshot']()['uid'], [1,2,1,0,1,1,4])
        self.assertEqual(namespace['_bench_snapshot_times']['per_uid_monotonic'], {'uid': 10})
        lock.acquire.return_value = False
        with self.assertRaises(RuntimeError):
            namespace['_bench_snapshot']()

    def test_provenance_rejects_a_changed_load_tester(self):
        fixture = runner.ROOT / 'bench/fixtures/tester/tak_tester.py.txt'
        result = sustained.provenance({'name': 'baseline'}, 'a'*40, fixture)
        self.assertEqual(result['tester_commit'], '5187abd46d827d37cfc5708805eced197a837e49')
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / 'tester.py'
            changed.write_text(fixture.read_text()+'# changed')
            with self.assertRaises(ValueError):
                sustained.provenance({'name': 'baseline'}, 'a'*40, changed)

    def test_load_driver_keeps_one_process_and_orders_boundaries(self):
        boundary = Mock()
        with tempfile.TemporaryDirectory() as directory:
            tester = Path(directory) / 'tester.py'
            tester.write_text((runner.ROOT / 'bench/fixtures/tester/tak_tester.py.txt').read_text())
            forward, client = Mock(), Mock()
            forward.poll.return_value = 0
            client.poll.return_value = None
            client.returncode = 0
            def launch(*args, **kwargs):
                if 'env' not in kwargs:
                    return forward
                Path(kwargs['env']['BENCH_WINDOW_READY']).write_text('{}')
                kwargs['stdout'].write('BENCH_WINDOW_JSON:' + json.dumps(self.window()) + '\n')
                return client
            original_touch = Path.touch
            def touch(path, *args, **kwargs):
                result = original_touch(path, *args, **kwargs)
                if path.name == 'go':
                    (path.parent / 'start').write_text('{}')
                    (path.parent / 'end').write_text('{}')
                return result
            with patch.object(runner.subprocess, 'run'), patch.object(runner.subprocess, 'Popen', side_effect=launch) as popen, patch.object(runner, 'kubectl_cmd', return_value=['fixture']), patch.object(runner, 'kill_group'), patch.object(runner.time, 'sleep'), patch.object(sustained, 'WARMUP', 0), patch.object(Path, 'touch', touch):
                result = runner.run_load(50, 1200, 'fixture-password', tester, study=True, boundary=boundary)
            self.assertEqual([call.args[0] for call in boundary.call_args_list], ['before', 'started', 'after'])
            self.assertEqual(popen.call_count, 2)  # one port-forward, one live client parent
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index('--interval')+1], '5')
            self.assertEqual(result['observed_stable_clients'], 50)

    def test_report_cohort_isolates_short_protocol_and_invalid_study(self):
        value = {'git_sha': 'a'*40, 'arch': 'amd64', 'config': 'baseline-r1', 'study': {'protocol': 'synthetic-baseline-v1', 'measurement_s': 1200, 'warmup_s': 300, 'self_sa_interval_s': 5, 'tester_sha256': 'b'*64},
                 'load': {**self.parse(self.window()), 'clients': 50}, 'kubelet': {'steady_rss_bytes': 100}, 'errors': []}
        second = copy.deepcopy(value)
        second['load']['duration_s'] += 0.2
        short = copy.deepcopy(value)
        short.pop('study')
        self.assertEqual(len(report.cohorts([value, second, short])), 2)
        value['errors'] = ['unstable boundary']
        self.assertIsNone(report.point(value)['throughput'])
        self.assertIn('Synthetic baseline repeats', '\n'.join(report.study_lines([value])))

    def test_three_repeat_plan_stops_after_invalid_record(self):
        proof = {'cluster': 'owned'}
        ephemeral = SimpleNamespace(verify=Mock(return_value=proof))
        spec = SimpleNamespace(loader=Mock())
        valid = {'errors': [], 'images': {'sum_bytes': 1}}
        invalid = {'errors': ['reconnected'], 'images': {'sum_bytes': 1}}
        with patch.dict(os.environ, {'BENCH_STUDY': 'synthetic-baseline', 'BENCH_PROFILE': 'baseline', 'BENCH_CLIENTS': '50'}), patch.object(runner.shutil, 'which', return_value='fixture'), patch.object(runner.importlib.util, 'spec_from_file_location', return_value=spec), patch.object(runner.importlib.util, 'module_from_spec', return_value=ephemeral), patch.object(runner, 'ready_age', return_value=(1, [])), patch.object(runner, 'snapshot', return_value=[]), patch.object(runner.sustained, 'provenance', return_value={'protocol': 'fixture'}), patch.object(runner, 'one', side_effect=[valid, invalid]) as one, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main([]), 1)
        self.assertEqual(one.call_count, 2)
        self.assertEqual([call.args[0]['name'] for call in one.call_args_list], ['baseline-r1', 'baseline-r2'])
        self.assertEqual(ephemeral.verify.call_count, 3)

    def test_workflow_keeps_one_install_and_requires_owned_cluster(self):
        source = (runner.ROOT / '.github/workflows/benchmark.yaml').read_text()
        self.assertEqual(source.count('name: Install the current branch'), 1)
        self.assertIn('ephemeral-cluster.py bootstrap --context k3d-uds', source)
        self.assertIn('ephemeral-cluster.py mark --context k3d-uds', source)
        self.assertIn("BENCH_STUDY: ${{ github.event.inputs.study || 'short' }}", source)

class CollectorIntegrationTests(unittest.TestCase):
    def collect(self, before_query_seconds=0.2):
        from datetime import datetime, timezone
        from tests.test_bench_capacity import pod
        current = [1000.0]
        reads = [0]
        sample_count = [0]
        target = pod(uid='pg-uid', limit='512Mi')
        target['metadata']['name'] = 'takserver-postgresql-0'
        target['spec']['containers'][0]['name'] = 'postgresql'
        target['status']['containerStatuses'][0].update(name='postgresql', containerID='containerd://'+'a'*64, imageID='sha256:'+'b'*64)
        def kube(*args, **kwargs):
            if args[:2] == ('get', 'nodes'):
                return SimpleNamespace(stdout='node/k3d-uds-server-0')
            if args[:2] == ('get', '--raw'):
                sample_count[0] += 1
                stamp = datetime.fromtimestamp(1000 + before_query_seconds + 0.2 + sample_count[0]*5, timezone.utc).isoformat()
                value = {'pods': [{'podRef': {'namespace': 'takserver', 'uid': 'pg-uid', 'name': 'takserver-postgresql-0'},
                         'containers': [{'name': 'postgresql', 'memory': {'time': stamp, 'workingSetBytes': 123}, 'cpu': {'time': stamp, 'usageNanoCores': 45}}]}]}
                return SimpleNamespace(stdout=json.dumps(value))
            if args[:2] == ('get', 'pods'):
                return SimpleNamespace(stdout=json.dumps({'items': [] if 'cloudtak' in args else [target]}))
            if 'cat' in args:
                return SimpleNamespace(stdout='536870912' if args[-1].endswith('memory.max') else '50000 100000')
            if any('postgis_lib_version' in str(a) for a in args):
                return SimpleNamespace(stdout='{"server_version_num":"180006","postgis_version":"3.6.4"}')
            reads[0] += 1
            current[0] += before_query_seconds if reads[0] == 1 else 0.2
            row = {key: 100 if reads[0] == 1 else 120 for key in sustained.DB_COUNTERS}
            row.update({key: None for key in ('stats_reset_database','stats_reset_checkpointer','stats_reset_io')})
            row.update({key: '128MB' for key in runner.POSTGRES_SETTINGS})
            return SimpleNamespace(stdout=json.dumps(row))
        class Stop:
            stopped = False
            polls = 0
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
            def wait(self, _seconds):
                self.polls += 1
                if self.polls == 240: self.stopped = True
        class Thread:
            ident = None
            def __init__(self, target, args, **kwargs): self.target, self.args = target, args
            def start(self):
                self.ident = 1
                self.target(*self.args)
            def join(self, **kwargs): pass
            def is_alive(self): return False
        def load(*args, **kwargs):
            callback = kwargs['boundary']
            callback('before')
            current[0] += 0.2
            start = current[0]
            callback('started')
            current[0] += 1200.5
            end = current[0]
            callback('after')
            value = SustainedTests().window()
            value.update(start_unix=start, end_unix=end)
            return sustained.parse_window('BENCH_WINDOW_JSON:'+json.dumps(value))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'BENCH_STUDY': 'synthetic-baseline', 'BENCH_PROFILE': 'baseline', 'BENCH_CLIENTS': '50'}), patch.object(runner, 'kubectl', side_effect=kube), patch.object(runner, 'footprint', return_value=({}, [])), patch.object(runner, 'start_phases', return_value=({}, [])), patch.object(runner, 'startup_shape', return_value=({}, [])), patch.object(runner, 'package_bytes', return_value=1), patch.object(runner, 'image_bytes', return_value={'sum_bytes': 1}), patch.object(runner, 'keystore_password', return_value='fixture'), patch.object(runner, 'run_load', side_effect=load), patch.object(runner.threading, 'Event', Stop), patch.object(runner.threading, 'Thread', Thread), patch.object(runner.time, 'time', side_effect=lambda: current[0]), contextlib.redirect_stdout(io.StringIO()):
            return runner.one({'name':'baseline-r1','duration_s':1200,'env':[],'resources':[],'restart':False,'study':{}}, 50, Path(directory), Path('fixture'), 1, study=True)

    def test_nonempty_memory_cgroup_and_actual_boundary_callbacks(self):
        value = self.collect()
        self.assertEqual(value['errors'], [])
        self.assertEqual(value['kubelet']['peak_cpu_nanocores'], 45)
        self.assertEqual(value['postgres']['checkpoints_timed'], 20)
        self.assertEqual(value['study']['cgroup_before']['memory.max'], '536870912')
        self.assertEqual(len(value['study']['memory_samples']), 240)
        self.assertEqual(value['capacity']['containers'][0]['samples']['memory_sample_count'], 240)

    def test_slow_before_query_invalidates_whole_sql_bracket(self):
        value = self.collect(before_query_seconds=7)
        self.assertTrue(any('five-second bracket' in error for error in value['errors']))


if __name__ == '__main__':
    unittest.main()
