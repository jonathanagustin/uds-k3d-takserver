#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
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
        pod = {'metadata': {'uid': UID, 'name': 'agent-hook-abcd'}, 'spec': {'nodeName': 'k3d-trial-server-0'},
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

    def test_child_deadline_and_no_raw_errors(self):
        with patch.object(w.time, 'monotonic', return_value=10), patch.object(w.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(w.Unavailable, '^command-or-size$'):
                w.Commands(12).run('mock-only')
            args, kwargs = run.call_args
            self.assertEqual(args[0][:3], ['timeout', '--kill-after=0.1s', '1.2s'])
            self.assertEqual(kwargs['timeout'], 2)
            self.assertEqual(kwargs['stderr'], w.subprocess.DEVNULL)
        with patch.object(w.time, 'monotonic', return_value=10):
            with self.assertRaisesRegex(w.Unavailable, '^deadline$'):
                w.Commands(9).run('never-executed')

    def test_snapshot_exact_commands_and_pid_race(self):
        cmd = Mock()
        cmd.run.side_effect = [CID + ' 12 RUNNING', '0::/' + CID, 'usage_usec 3', 'max 100000', '100', 'max', 'oom 0', CID + ' 13 RUNNING']
        with self.assertRaisesRegex(w.Unavailable, 'identity-changed'):
            w.snapshot(cmd, {'node': 'k3d-trial-server-0', 'containerID': 'containerd://' + CID})
        args = [c.args for c in cmd.run.call_args_list]
        self.assertTrue(all(a[:5] == ('docker', 'exec', 'k3d-trial-server-0', 'timeout', '1') for a in args))
        self.assertFalse(any('inspect' in a or 'logs' in a for a in args))


if __name__ == '__main__':
    unittest.main()
