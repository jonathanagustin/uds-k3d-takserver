# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise complete redacted media errors, bounds, and pre-deploy ordering."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import time
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('owned_media', ROOT/'demo/media_command.py')
MEDIA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEDIA)


class MediaTests(unittest.TestCase):
    def test_success_retains_stdout_for_style_coordinate_and_ffprobe_consumers(self):
        result = MEDIA.run_media([sys.executable, '-c', 'print("48 60")'])
        self.assertEqual(result.stdout, '48 60\n')

    def test_failure_prints_real_diagnostic_but_no_secret_or_argument_dump(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaisesRegex(RuntimeError, 'sanitized diagnostic'):
            MEDIA.run_media([sys.executable, '-c', 'import sys;print("font missing password=PRIVATE_MEDIA_PASSWORD",file=sys.stderr);sys.exit(1)'])
        self.assertIn('font missing', error.getvalue())
        self.assertNotIn('PRIVATE_MEDIA_PASSWORD', error.getvalue())

    def test_failed_incomplete_and_oversized_streams_are_omitted_whole(self):
        for command, options in [
            ('import sys,time;print("PARTIAL_SECRET",file=sys.stderr,flush=True);time.sleep(5)', {'seconds':.15}),
            ('import sys;print("PARTIAL_SECRET"+"x"*4096,file=sys.stderr);sys.exit(1)', {'byte_limit':128}),
            ('import sys;sys.stderr.buffer.write(b"PARTIAL_SECRET\\x00");sys.exit(1)', {}),
        ]:
            error = io.StringIO()
            started = time.monotonic()
            with contextlib.redirect_stderr(error), self.assertRaises(RuntimeError):
                MEDIA.run_media([sys.executable, '-c', command], **options)
            self.assertNotIn('PARTIAL_SECRET', error.getvalue())
            self.assertIn('omitted:', error.getvalue())
            self.assertLess(time.monotonic()-started, 3)

    def test_verified_musl_pipeline_is_checked_before_cluster_deployment(self):
        workflow = yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['env']['AGG_SHA256'], 'ddcbf6ca044c8ac3a434dcb9ee89fb9e3be87209982b7c2adb55f782e8f0f390')
        steps = workflow['jobs']['record']['steps']
        preflight = next(s for s in steps if s['name']=='Check the pinned media pipeline before deployment')
        deploy = next(s for s in steps if s['name']=='Deploy UDS Core and TAK')
        render = next(s for s in steps if s['name']=='Render the recorded deployment')
        self.assertLess(steps.index(preflight), steps.index(deploy))
        self.assertIn('agg-x86_64-unknown-linux-musl', preflight['run'])
        self.assertIn('sha256sum -c -', preflight['run'])
        self.assertIn('check-media.py', preflight['run'])
        self.assertNotIn('curl', render['run'])


if __name__ == '__main__': unittest.main()
