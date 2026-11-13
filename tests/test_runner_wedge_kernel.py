# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Kernel-evidence policy and real bounded subprocess controls; no host SysRq."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kernel_evidence', ROOT / '.github/scripts/runner-wedge-kernel.py')
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class KernelEvidenceTests(unittest.TestCase):
    def run_policy(self, stalled, root, before='healthy kernel', outcomes=None):
        calls, lines = [], []
        def capture(argv, seconds, deadline):
            calls.append((argv, seconds))
            if outcomes:
                return outcomes(len(calls), argv)
            return (before if len(calls) == 1 else 'complete body'), 'complete'
        with patch.object(kernel, 'capture', capture):
            kernel.collect(stalled, root, lines.append)
        return calls, '\n'.join(lines)

    def test_healthy_route_and_kernel_never_request_sysrq_or_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            calls, text = self.run_policy(False, Path(temp))
        self.assertEqual([a for a, _ in calls], [['sudo', '-n', 'dmesg', '-T']])
        self.assertIn('No sign', text)

    def test_route_timeout_collects_full_traces_sysrq_once_and_modules(self):
        trace = 'INFO: task ip blocked for more than 120 seconds\nCall Trace:\n rtnl_lock+0x1/0x2\n cleanup_net+0x3/0x4\n'
        with tempfile.TemporaryDirectory() as temp:
            calls, text = self.run_policy(True, Path(temp), trace)
        self.assertEqual([a for a, _ in calls], [
            ['sudo', '-n', 'dmesg', '-T'],
            ['sudo', '-n', 'sh', '-c', 'printf w > /proc/sysrq-trigger'],
            ['sudo', '-n', 'dmesg', '-T'], ['lsmod']])
        self.assertEqual([s for _, s in calls], [3, 2, 3, 2])
        self.assertIn(trace, text)
        self.assertIn('cause remains unproven', text)

    def test_repeated_probe_does_not_repeat_even_a_failed_sysrq(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, text = self.run_policy(True, root, outcomes=lambda n, a: (None, 'command-failed') if a[2:3] == ['sh'] else ('body', 'complete'))
            second, second_text = self.run_policy(True, root)
        self.assertEqual(sum(a[2:3] == ['sh'] for a, _ in first + second), 1)
        self.assertIn('sysrq-w: command-failed', text)
        self.assertIn('already claimed', second_text)

    def test_hung_kernel_with_healthy_route_preserves_trace_without_sysrq(self):
        with tempfile.TemporaryDirectory() as temp:
            calls, text = self.run_policy(False, Path(temp), 'task blocked for more than 120 seconds\n full_unmatched_frame')
        self.assertEqual([a for a, _ in calls], [['sudo', '-n', 'dmesg', '-T'], ['lsmod']])
        self.assertIn('full_unmatched_frame', text)

    def test_collection_failure_never_claims_no_kernel_problem(self):
        with tempfile.TemporaryDirectory() as temp:
            _, text = self.run_policy(False, Path(temp), outcomes=lambda n, a: (None, 'timeout'))
        self.assertIn('inconclusive', text)
        self.assertNotIn('No sign', text)

    def test_complete_redaction_precedes_output_including_multiline_key(self):
        raw = 'task blocked for more than 120 seconds\nCall Trace:\n cleanup_net\npassword=synthetic-secret\n-----BEGIN PRIVATE KEY-----\nsynthetic-key-body\n-----END PRIVATE KEY-----\nlast_frame\n'
        text, status = kernel.capture([sys.executable, '-I', '-B', '-c', 'import sys;sys.stdout.write(' + repr(raw) + ')'], 2, time.monotonic()+3)
        self.assertEqual(status, 'complete')
        self.assertIn('cleanup_net', text)
        self.assertIn('last_frame', text)
        self.assertNotIn('synthetic-secret', text)
        self.assertNotIn('synthetic-key-body', text)

    def test_timeout_omits_all_partial_streams_and_stops_owned_process(self):
        start = time.monotonic()
        text, status = kernel.capture([sys.executable, '-I', '-B', '-c', 'import time;print("partial",flush=True);time.sleep(30)'], .05, start+1)
        self.assertEqual((text, status), (None, 'timeout'))
        self.assertLess(time.monotonic()-start, 1)

    def test_oversized_stream_is_omitted_without_truncated_evidence(self):
        with patch.object(kernel, 'LIMIT', 128):
            text, status = kernel.capture([sys.executable, '-I', '-B', '-c', 'import os;os.write(1,b"x"*100);os.write(2,b"y"*100)'], 2, time.monotonic()+3)
        self.assertEqual((text, status), (None, 'output-limit'))

    def test_non_text_stream_and_failed_command_are_omitted(self):
        text, status = kernel.capture([sys.executable, '-I', '-B', '-c', 'import os;os.write(1,b"\\xff")'], 2, time.monotonic()+3)
        self.assertEqual((text, status), (None, 'unsanitizable'))
        text, status = kernel.capture([sys.executable, '-I', '-B', '-c', 'print("partial");raise SystemExit(2)'], 2, time.monotonic()+3)
        self.assertEqual((text, status), (None, 'command-failed'))

    def test_aggregate_deadline_does_not_spawn_another_command(self):
        with patch.object(subprocess, 'Popen') as popen:
            self.assertEqual(kernel.capture(['never'], 5, time.monotonic()-1), (None, 'deadline'))
            popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
