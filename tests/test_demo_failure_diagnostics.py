# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise failure capture/redaction without a cluster or workflow run."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class DemoDiagnosticsTests(unittest.TestCase):
    def test_complete_logs_are_redacted_and_failed_or_oversized_logs_are_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('demo-failure-diagnostics.sh', 'redact-then-filter.sh', 'redact-logs.py'):
                shutil.copyfile(ROOT / '.github/scripts' / name, root / name)
                (root / name).chmod(0o755)
            dump = root / 'dump-memory.sh'
            dump.write_text('#!/bin/sh\necho memory-evidence\n')
            dump.chmod(0o755)
            uds = root / 'uds'
            uds.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if '--previous' in sys.argv:
 print('FAILED_CAPTURE_MUST_NOT_SURVIVE');sys.exit(1)
if 'wait-deps' in sys.argv:
 print('OVERSIZED_MUST_NOT_SURVIVE'+'x'*4194305);sys.exit(0)
print('startup-evidence password=PRIVATE_PASSWORD')
''')
            uds.chmod(0o755)
            output = root / 'sanitized'
            result = subprocess.run(['bash', str(root / 'demo-failure-diagnostics.sh'), str(output)],
                                    env={**os.environ, 'PATH':str(root)+os.pathsep+os.environ['PATH'],
                                         'CALLS':str(root/'calls')}, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = (output/'tak-startup.log').read_text()
            self.assertIn('memory-evidence', report)
            self.assertIn('startup-evidence', report)
            for forbidden in ('PRIVATE_PASSWORD', 'FAILED_CAPTURE_MUST_NOT_SURVIVE', 'OVERSIZED_MUST_NOT_SURVIVE'):
                self.assertNotIn(forbidden, report)
                self.assertNotIn(forbidden.encode(), result.stdout)
            self.assertEqual(len((root/'calls').read_text().splitlines()), 16)
            self.assertEqual(list(output.iterdir()), [output/'tak-startup.log'])

    def test_runner_override_and_finished_sanitizer_gate(self):
        workflow = yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(), Loader=yaml.BaseLoader)
        record = workflow['jobs']['record']
        self.assertEqual(record['runs-on'], "${{ vars.TEST_RUNNER || 'ubuntu-22.04' }}")
        steps = record['steps']
        trim = next(s for s in steps if s['name']=='Trim the runner')
        self.assertIn("vars.TEST_RUNNER == 'ubuntu-22.04'", trim['if'])
        capture = next(s for s in steps if s.get('id')=='startup-diagnostics')
        upload = next(s for s in steps if s['name']=='Retain sanitized startup diagnostics')
        segments = next(s for s in steps if s['name']=='Upload the separate segments')
        self.assertLess(steps.index(capture), steps.index(upload))
        self.assertLess(steps.index(upload), steps.index(segments))
        self.assertEqual(capture['timeout-minutes'], '5')
        self.assertEqual(upload['timeout-minutes'], '3')
        self.assertEqual(segments['timeout-minutes'], '10')
        self.assertIn('!cancelled()', upload['if'])
        self.assertIn("steps.startup-diagnostics.outcome == 'success'", upload['if'])
        self.assertEqual(upload['with']['path'], '${{ runner.temp }}/demo-failure-sanitized/tak-startup.log')


if __name__ == '__main__':
    unittest.main()
