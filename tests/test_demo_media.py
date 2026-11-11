# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise complete redacted media errors, bounds, and pre-deploy ordering."""
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('owned_media', ROOT/'demo/media_command.py')
MEDIA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEDIA)
sys.path.insert(0, str(ROOT/'demo'))
import filters as FILTERS


class MediaTests(unittest.TestCase):
    def test_success_retains_stdout_for_style_coordinate_and_ffprobe_consumers(self):
        result = MEDIA.run_media([sys.executable, '-c', 'print("48 60")'])
        self.assertEqual(result.stdout, '48 60\n')

    def test_production_budget_is_separate_from_short_preflight(self):
        self.assertEqual(MEDIA.PRODUCTION_SECONDS, 1800)
        with patch.dict(MEDIA.os.environ, {'DEMO_MEDIA_COMMAND_SECONDS':'.15'}):
            error = io.StringIO()
            with contextlib.redirect_stderr(error), self.assertRaises(MEDIA.MediaCommandError):
                MEDIA.run_media([sys.executable, '-c', 'import time;time.sleep(5)'])
            self.assertIn('time or size bound', error.getvalue())
        result = MEDIA.run_media([sys.executable, '-c', 'import sys;print("metadata");print("private diagnostic",file=sys.stderr)'])
        self.assertEqual(result.stdout, 'metadata\n')
        self.assertEqual(result.stderr, 'private diagnostic\n')

    def test_failure_prints_real_diagnostic_but_no_secret_or_argument_dump(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaisesRegex(MEDIA.MediaCommandError, 'sanitized diagnostic') as failed:
            MEDIA.run_media([sys.executable, '-c', 'import sys;print("font missing password=PRIVATE_MEDIA_PASSWORD",file=sys.stderr);sys.exit(1)'])
        self.assertIn('font missing', error.getvalue())
        self.assertNotIn('PRIVATE_MEDIA_PASSWORD', error.getvalue())
        self.assertEqual(failed.exception.cmd, '<media command>')
        self.assertEqual(failed.exception.stdout, '')
        self.assertNotIn('PRIVATE_MEDIA_PASSWORD', failed.exception.stderr)
        self.assertNotIn('PRIVATE_MEDIA_PASSWORD', str(failed.exception))

    def test_failed_incomplete_and_oversized_streams_are_omitted_whole(self):
        for command, options in [
            ('import sys,time;print("PARTIAL_SECRET",file=sys.stderr,flush=True);time.sleep(5)', {'seconds':.15}),
            ('import sys;print("PARTIAL_SECRET"+"x"*4096,file=sys.stderr);sys.exit(1)', {'byte_limit':128}),
            ('import sys;sys.stderr.buffer.write(b"PARTIAL_SECRET\\x00");sys.exit(1)', {}),
            ('print("PARTIAL_SECRET"+"x"*4096)', {'stdout_limit':128}),
        ]:
            error = io.StringIO()
            started = time.monotonic()
            with contextlib.redirect_stderr(error), self.assertRaises(MEDIA.MediaCommandError):
                MEDIA.run_media([sys.executable, '-c', command], **options)
            self.assertNotIn('PARTIAL_SECRET', error.getvalue())
            self.assertIn('omitted:', error.getvalue())
            self.assertLess(time.monotonic()-started, 3)

    def test_optional_phone_failure_uses_existing_browser_fallback_with_redacted_excerpt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root/'events.json'
            events.write_text(json.dumps([{'kind':'start','at':0,'value':'0'},
                {'kind':'phone-on','at':0,'value':'0,0,4,4'}]))
            device = root/'device.mp4';device.write_bytes(b'explicit device fixture')
            output = root/'prepared.mp4'
            commands = []
            def run(*args):
                commands.append(args)
                if args[0] == 'ffprobe':
                    return subprocess.CompletedProcess(args,0,stdout='64,64' if 'stream=width,height' in args else '64',stderr='')
                if '[c2]' in args:
                    code = "import sys;sys.stderr.write(" + repr('<Config password="PRIVATE_START\nPRIVATE_FRAGMENT"/>\noptional compositor failed\n') + ");sys.exit(1)"
                    return FILTERS.run_media([sys.executable,'-c',code])
                self.assertIn('[c1]',args)
                Path(args[-1]).write_bytes(b'browser fallback accepted')
                return FILTERS.run_media([sys.executable,'-c','print("fallback accepted")'])
            error = io.StringIO()
            with patch.object(FILTERS,'duration_of',return_value=1), patch.object(FILTERS,'chrome_rows',return_value=(0,2,'0x000000')), \
                    patch.object(FILTERS,'blank_ranges',return_value=[]), patch.object(FILTERS,'align',return_value=0), \
                    patch.object(FILTERS,'stall_cuts',return_value=[]), patch.object(FILTERS,'phone_video',return_value=[]), \
                    patch.object(FILTERS,'run',side_effect=run), contextlib.redirect_stderr(error):
                FILTERS.prepare('explicit-browser-fixture',str(events),str(output),str(root/'prepared.json'),str(device))
            self.assertEqual(output.read_bytes(),b'browser fallback accepted')
            self.assertEqual(sum('[c2]' in args for args in commands),1)
            self.assertEqual(sum('[c1]' in args for args in commands),1)
            self.assertIn('phone: device recording not used:',error.getvalue())
            self.assertIn('optional compositor failed',error.getvalue())
            self.assertNotIn('PRIVATE_START',error.getvalue())
            self.assertNotIn('PRIVATE_FRAGMENT',error.getvalue())

    def test_unit_media_dependencies_are_explicit_in_the_test_environment(self):
        workflow = yaml.load((ROOT/'.github/workflows/unit-tests.yaml').read_text(), Loader=yaml.BaseLoader)
        step = next(s for s in workflow['jobs']['coverage']['steps'] if s['name']=='Config secret redaction')
        self.assertEqual(step['env']['PYYAML_VERSION'], '6.0.3')
        self.assertEqual(step['env']['PILLOW_VERSION'], '13.0.0')
        command = step['run'].splitlines()[0]
        self.assertIn('uv run --no-project', command)
        self.assertIn('--with "pyyaml==${PYYAML_VERSION}"', command)
        self.assertIn('--with "pillow==${PILLOW_VERSION}"', command)
        self.assertIn('tests.test_demo_media', command)

    def test_docs_browser_keeps_dependency_checks_with_a_finite_install_budget(self):
        workflow = yaml.load((ROOT/'.github/workflows/docs.yaml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['jobs']['build']['runs-on'], 'ubuntu-24.04')
        steps = workflow['jobs']['build']['steps']
        prepare = next(s for s in steps if s['name']=='Prepare bounded signed Ubuntu package indexes')
        install = next(s for s in steps if s['name']=='Install the docs browser')
        browser = next(s for s in steps if s['name']=='Browser tests')
        self.assertLess(steps.index(prepare), steps.index(install))
        self.assertLess(steps.index(install), steps.index(browser))
        self.assertEqual(prepare['run'], 'sudo python3 .github/scripts/ci-apt.py update')
        self.assertEqual(prepare['timeout-minutes'], '3')
        self.assertEqual(install['timeout-minutes'], '3')
        self.assertEqual(install['run'], 'timeout --kill-after=5 150 npx playwright install --with-deps chromium')
        for event in ('pull_request', 'push'):
            self.assertIn('.github/scripts/ci-apt.py', workflow['on'][event]['paths'])

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
