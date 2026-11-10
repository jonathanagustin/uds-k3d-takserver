#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import unittest
import os
import sys
import tempfile
import time
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('watch', Path(__file__).with_name('upgrade-agent-watch.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
CID = 'a' * 64
UID = '12345678-1234-1234-1234-123456789abc'


class WatchTests(unittest.TestCase):
    def event(self):
        return {'metadata': {'uid': UID, 'containerStartedAt': 1}, 'involvedObject': {'uid': UID, 'fieldPath': 'spec.containers{server}'},
                'reason': 'Unhealthy', 'message': 'Liveness probe failed: SECRET_URL', 'count': 3,
                'lastTimestamp': '2026-11-10T02:00:00Z'}

    def test_live_event_not_history_or_readiness(self):
        e = self.event()
        start = w.stamp('2026-11-10T01:59:59Z')
        self.assertTrue(w.live_failure(e, {'uid': UID, 'containerStartedAt': 1}, {UID: 2}, start))
        self.assertFalse(w.live_failure(e, {'uid': UID, 'containerStartedAt': 1}, {UID: 3}, start))
        self.assertFalse(w.live_failure(e, {'uid': 'another', 'containerStartedAt': 1}, {}, start))
        self.assertFalse(w.live_failure(e, {'uid': UID, 'containerStartedAt': 1}, {}, start + 2))
        for message in ('Readiness probe failed:', 'Startup probe failed:'):
            e['message'] = message
            self.assertFalse(w.live_failure(e, {'uid': UID, 'containerStartedAt': 1}, {}, start))

    def test_exact_task_and_protocol(self):
        self.assertEqual(w.task_pid('TASK PID STATUS\n' + CID + ' 123 RUNNING\n', CID), '123')
        for text in (CID[:12] + ' 123 RUNNING', CID + ' 0 RUNNING', CID + ' 123 STOPPED'):
            with self.assertRaises(w.Unavailable):
                w.task_pid(text, CID)
        pod = {'metadata': {'uid': UID, 'name': 'agent-hook-abcd'}, 'spec': {'nodeName': 'k3d-uds-server-0'},
               'status': {'containerStatuses': [{'name': 'server', 'containerID': 'containerd://' + CID, 'state': {'running': {'startedAt': '2026-11-10T01:00:00Z'}}}]}}
        self.assertEqual(w.identity(pod)['containerID'], 'containerd://' + CID)
        pod['status']['containerStatuses'][0]['containerID'] = 'docker://' + CID
        with self.assertRaises(w.Unavailable):
            w.identity(pod)

    def test_path_rejects_traversal_other_container_and_v1(self):
        self.assertEqual(w.cgroup_path('0::/kubepods.slice/cri-containerd-' + CID + '.scope\n', CID),
                         '/sys/fs/cgroup/kubepods.slice/cri-containerd-' + CID + '.scope')
        for text in ('0::/../' + CID, '0::/other', '1:cpu:/' + CID, '0::/' + CID + '\n0::/other'):
            with self.assertRaises(w.Unavailable):
                w.cgroup_path(text, CID)

    def test_metric_schema_never_passes_payload(self):
        self.assertEqual(w.metric('cpu.stat', 'usage_usec 100\nnr_throttled 2\n'), {'usage_usec': 100, 'nr_throttled': 2})
        for name, text in [('cpu.stat', 'secret https://credential'), ('cpu.max', 'max SECRET'), ('memory.current', '-1')]:
            with self.assertRaises(w.Unavailable):
                w.metric(name, text)

    def test_explicit_context_and_shared_proof(self):
        cmd = Mock()
        cmd.run.return_value = '{}'
        w.Commands.kube(cmd, 'get', 'events')
        self.assertIn('--context', cmd.run.call_args.args)
        self.assertIn('k3d-uds', cmd.run.call_args.args)
        with patch.object(w.ephemeral, 'verify', return_value={'clusterUID': 'one'}) as verify:
            self.assertEqual(w.guard(cmd), {'clusterUID': 'one'})
            verify.assert_called_once()
            with self.assertRaisesRegex(w.Unavailable, 'proof-changed'):
                w.guard(cmd, {'clusterUID': 'another'})

    def test_observe_revalidates_proof_and_emits_only_allowlisted_event(self):
        pod = {'metadata': {'uid': UID, 'name': 'agent-hook-abcd'},
               'spec': {'nodeName': 'k3d-uds-server-0'},
               'status': {'containerStatuses': [{'name': 'server', 'restartCount': 0,
                          'containerID': 'containerd://' + CID,
                          'state': {'running': {'startedAt': '2026-11-10T01:00:00Z'}}}]}}
        cmd = Mock()
        cmd.kube.side_effect = [{'items': []}, {'spec': {'selector': {'app': 'agent-hook'}}},
                                {'items': [pod]}, {'items': [self.event()]}, pod, pod]
        output = io.StringIO()
        with patch.object(w, 'Commands', return_value=cmd), patch.object(w, 'guard', return_value={'proof': 1}) as guard, patch.object(w, 'snapshot', return_value={'metrics': {}}), patch.object(w.time, 'time', return_value=100), contextlib.redirect_stdout(output):
            self.assertEqual(w.observe(20), 0)
        self.assertEqual(guard.call_args_list[1].args, (cmd, {'proof': 1}))
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[1]['watch'], 'first-live-liveness-failure')
        self.assertNotIn('SECRET_URL', output.getvalue())
        self.assertEqual(rows[1]['eventCount'], 3)

    def test_outer_timeout_cleans_actual_ignoring_descendant(self):
        # Bypass GNU timeout to force the outer deadline path; execute real
        # Python processes, including a descendant that ignores SIGTERM.
        actual_popen = w.subprocess.Popen
        def popen(argv, **kwargs):
            return actual_popen(argv[4:], **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            code = ("import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    "pid=os.fork(); "
                    "open(" + repr(str(pidfile)) + ",'w').write(str(os.getpid())) if pid==0 else None; "
                    "time.sleep(30)")
            with patch.object(w.subprocess, 'Popen', side_effect=popen):
                with self.assertRaisesRegex(w.Unavailable, 'command-unavailable'):
                    w.Commands(time.monotonic() + 0.4).run(sys.executable, '-c', code)
            pid = int(pidfile.read_text())
            for _ in range(50):
                proc = Path('/proc') / str(pid) / 'stat'
                if not proc.exists() or proc.read_text().split()[2] == 'Z':
                    break
                time.sleep(0.01)
            else:
                os.kill(pid, 9)
                self.fail('SIGTERM-ignoring descendant survived group cleanup')

    def test_snapshot_exact_commands_and_pid_race(self):
        cmd = Mock()
        cmd.run.side_effect = [CID + ' 12 RUNNING', '0::/' + CID, 'usage_usec 3', 'max 100000', '100', 'max', 'oom 0', CID + ' 13 RUNNING']
        with self.assertRaisesRegex(w.Unavailable, 'identity-changed'):
            w.snapshot(cmd, {'node': 'k3d-uds-server-0', 'containerID': 'containerd://' + CID})
        args = [c.args for c in cmd.run.call_args_list]
        self.assertTrue(all(a[:5] == ('docker', 'exec', 'k3d-uds-server-0', 'timeout', '1') for a in args))
        self.assertFalse(any('inspect' in a or 'logs' in a for a in args))


if __name__ == '__main__':
    unittest.main()
