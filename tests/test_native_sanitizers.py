# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Sanitizer flags and the scheduled native-sanitizer workflow contract."""
import importlib.util
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1'


class WorkflowLoader(yaml.SafeLoader):
    """PyYAML 1.1 would turn the workflow key `on` into True."""


def _workflow_bool(loader, node):
    value = loader.construct_scalar(node)
    if value.lower() in {'true', 'false'}:
        return value.lower() == 'true'
    return value


WorkflowLoader.add_constructor('tag:yaml.org,2002:bool', _workflow_bool)


def load_clock():
    path = ROOT / 'takx/compat/build-system-clock.py'
    spec = importlib.util.spec_from_file_location('clock_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeSanitizerTests(unittest.TestCase):
    def test_production_flags_stay_unsanitized(self):
        self.assertEqual(
            load_clock().shared_flags('gcc'),
            ['gcc', '-std=c11', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror'])

    def test_sanitizer_flags_enable_asan_and_ubsan(self):
        flags = load_clock().shared_flags('gcc', sanitize=True)
        self.assertIn('-fsanitize=address,undefined', flags)
        self.assertIn('-fno-omit-frame-pointer', flags)
        self.assertIn('-O1', flags)
        self.assertNotIn('-O2', flags)

    def test_workflow_runs_on_main_and_weekly(self):
        text = (ROOT / '.github/workflows/native-sanitizers.yaml').read_text()
        document = yaml.load(text, Loader=WorkflowLoader)
        self.assertNotIn('pull_request', document['on'])
        push = document['on']['push']
        self.assertEqual(push['branches'], ['main'])
        for path in (
            'takx/compat/src/main/native/**',
            'takx/compat/src/test/native/**',
            'takx/compat/build-system-clock.py',
            'takx/compat/test-system-clock.py',
            'takx/compat/src/main/java/android/os/SystemClock.java',
            'takx/compat/src/test/java/clock/**',
            '.github/workflows/native-sanitizers.yaml',
            'tests/test_native_sanitizers.py',
        ):
            self.assertIn(path, push['paths'])
        self.assertEqual(document['on']['schedule'], [{'cron': '30 4 * * 3'}])
        self.assertEqual(document['permissions'], {'contents': 'read'})
        job = document['jobs']['system-clock']
        self.assertEqual(job['timeout-minutes'], 10)
        self.assertIn(CHECKOUT, text)
        self.assertIn(CHECKOUT, (ROOT / '.github/workflows/codeql.yaml').read_text())
        step = job['steps'][1]
        self.assertEqual(step['env']['CC'], 'gcc')
        self.assertIn('python3 takx/compat/test-system-clock.py', step['run'])
        self.assertIn("github.event_name == 'push'", document['concurrency']['cancel-in-progress'])


if __name__ == '__main__':
    unittest.main()
