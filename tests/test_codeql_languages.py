# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""CodeQL language selection and the scheduled workflow contract."""
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WorkflowLoader(yaml.SafeLoader):
    """PyYAML 1.1 would turn the workflow key `on` into True."""


def _workflow_bool(loader, node):
    value = loader.construct_scalar(node)
    if value.lower() in {'true', 'false'}:
        return value.lower() == 'true'
    return value


WorkflowLoader.add_constructor('tag:yaml.org,2002:bool', _workflow_bool)


def load_selector():
    path = ROOT / '.github/scripts/codeql-languages.py'
    spec = importlib.util.spec_from_file_location('codeql_languages', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflow():
    text = (ROOT / '.github/workflows/codeql-extended.yaml').read_text()
    return text, yaml.load(text, Loader=WorkflowLoader)


class CodeQLLanguageTests(unittest.TestCase):
    def test_push_runs_only_the_languages_that_changed(self):
        selector = load_selector()
        cases = {
            'tests/test_foo.py': {'python': True, 'java': False, 'cpp': False},
            'script.pyi': {'python': True, 'java': False, 'cpp': False},
            'takx/CommonCommoSmoke.java': {'python': False, 'java': True, 'cpp': False},
            'tests/fixtures/distributed-configuration-init.java': {'python': False, 'java': True, 'cpp': False},
            'docs/Note.java': {'python': False, 'java': False, 'cpp': False},
            'takx/compat/src/main/native/system-clock.c': {'python': False, 'java': False, 'cpp': True},
            'takx/native-las/LibLASSourceProbe.cpp': {'python': False, 'java': False, 'cpp': True},
            'takx/native-cesium/ports/modp-base64/modp_b64_data.h': {'python': False, 'java': False, 'cpp': True},
            'README.md': {'python': False, 'java': False, 'cpp': False},
            'pepr/capabilities/oidc.ts': {'python': False, 'java': False, 'cpp': False},
        }
        for path, want in cases.items():
            with self.subTest(path=path):
                self.assertEqual(selector.classify([path]), want)
        self.assertEqual(
            selector.classify(['.github/workflows/codeql-extended.yaml']),
            {'python': True, 'java': True, 'cpp': True})
        self.assertEqual(
            selector.classify(['tests/test_foo.py', 'takx/compat/src/main/native/system-clock.c']),
            {'python': True, 'java': False, 'cpp': True})

    def test_schedule_scans_every_language_without_calling_github(self):
        selector = load_selector()

        def refuse(*_args, **_kwargs):
            raise AssertionError('schedule must not call the compare API')

        with patch.dict(os.environ, {'EVENT_NAME': 'schedule'}, clear=True):
            self.assertEqual(selector.decide(refuse), {'python': True, 'java': True, 'cpp': True})

    def test_changed_list_does_not_fetch(self):
        selector = load_selector()

        def refuse(*_args, **_kwargs):
            raise AssertionError('CHANGED must not call the compare API')

        with patch.dict(os.environ, {'CHANGED': 'takx/native-geos/GeosGeometry.c\n'}, clear=True):
            self.assertEqual(selector.decide(refuse), {'python': False, 'java': False, 'cpp': True})

    def test_missing_base_and_truncated_compare_scan_every_language(self):
        selector = load_selector()
        with patch.dict(os.environ, {'BEFORE': '0' * 40, 'AFTER': 'a' * 40, 'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True):
            self.assertIsNone(selector.fetch_changed(lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('fetch'))))
        files = [{'filename': f'file{i}.py'} for i in range(300)]

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def urlopen(_request, timeout):
            self.assertEqual(timeout, 30)
            return Response(json.dumps({'files': files}).encode())

        with patch.dict(os.environ, {'BEFORE': 'a' * 40, 'AFTER': 'b' * 40, 'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True):
            self.assertIsNone(selector.fetch_changed(urlopen))

        def one_file(_request, timeout):
            self.assertEqual(timeout, 30)
            return Response(json.dumps({'files': [{'filename': 'takx/ui-java/Probe.java'}]}).encode())

        with patch.dict(os.environ, {'BEFORE': 'a' * 40, 'AFTER': 'b' * 40, 'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True):
            self.assertEqual(selector.fetch_changed(one_file), ['takx/ui-java/Probe.java'])

    def test_workflow_is_main_and_weekly_and_reuses_codeql_pins(self):
        selector = load_selector()
        text, document = workflow()
        self.assertNotIn('pull_request', document['on'])
        self.assertEqual(document['on']['push']['branches'], ['main'])
        self.assertEqual(document['on']['push']['paths'], selector.push_paths())
        self.assertEqual(document['on']['schedule'], [{'cron': '0 5 * * 2'}])
        self.assertEqual(document['permissions'], {'contents': 'read'})
        codeql = (ROOT / '.github/workflows/codeql.yaml').read_text()
        called_text = (ROOT / '.github/workflows/codeql-language.yaml').read_text()
        called = yaml.load(called_text, Loader=WorkflowLoader)
        self.assertEqual(list(called['on']), ['workflow_call'])
        checkout = 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1'
        self.assertIn(checkout, text)
        for pin in (
            checkout,
            'github/codeql-action/init@1fc58d04a4d4374f921bdac573c3811c240f9c26 # v4.39.2',
            'github/codeql-action/analyze@1fc58d04a4d4374f921bdac573c3811c240f9c26 # v4.39.2',
        ):
            self.assertIn(pin, called_text)
            self.assertIn(pin, codeql)
        self.assertEqual(called['jobs']['analyze']['timeout-minutes'], 30)
        self.assertEqual(called['jobs']['analyze']['steps'][1]['with']['build-mode'], '${{ inputs.build-mode }}')
        callers = {
            'python': ('python', 'none'),
            'java': ('java-kotlin', 'none'),
            'cpp': ('c-cpp', 'none'),
        }
        for name, (language, build_mode) in callers.items():
            job = document['jobs'][name]
            self.assertEqual(job['if'], f"needs.scope.outputs.{name} == 'true'")
            self.assertEqual(job['uses'], './.github/workflows/codeql-language.yaml')
            self.assertEqual(job['with']['language'], language)
            self.assertEqual(job['with']['build-mode'], build_mode)
        configs = {name: yaml.safe_load(document['jobs'][name]['with']['config']) for name in callers}
        self.assertIn('upstream', configs['python']['paths-ignore'])
        self.assertEqual(configs['java']['paths'], ['takx', 'tests'])
        self.assertEqual(configs['cpp']['paths'], ['takx'])
        self.assertEqual(document['jobs']['scope']['timeout-minutes'], 5)
        self.assertIn('codeql-languages.py', document['jobs']['scope']['steps'][1]['run'])
        # The required JavaScript and Actions workflow stays unfiltered.
        required = yaml.load(codeql, Loader=WorkflowLoader)
        self.assertNotIn('paths', required['on'].get('pull_request') or {})
        self.assertNotIn('paths', required['on']['push'])


if __name__ == '__main__':
    unittest.main()
