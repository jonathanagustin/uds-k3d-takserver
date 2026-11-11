# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('conformance_check', HERE / 'check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Guards(unittest.TestCase):
    def test_offline_provenance(self):
        self.assertEqual(check.verify()['revision'], check.PIN)

    def copy(self, root):
        shutil.copytree(HERE / 'official', root / 'official')
        shutil.copy2(HERE / 'provenance.json', root / 'provenance.json')

    def test_altered_official_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.copy(root)
            (root / 'official/commoncommo/core/impl/protobuf/contact.proto').write_text('synthetic replacement')
            with self.assertRaises(AssertionError):
                check.verify(root)

    def test_wrong_revision_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.copy(root)
            p = root / 'provenance.json'
            x = json.loads(p.read_text())
            x['revision'] = '0' * 40
            p.write_text(json.dumps(x))
            with self.assertRaises(AssertionError):
                check.verify(root)

    def test_schema_is_actual_producer_variant(self):
        source = (HERE / 'official/commoncommo/core/impl/protobuf/contact.proto').read_text()
        self.assertIn('string altendpoints = 3;', source)
        self.assertEqual(sum(p.suffix == '.proto' for p in (HERE / 'official').rglob('*')), 10)

    def test_child_environment_preserves_home_and_blocks_injection(self):
        with patch.dict(os.environ, {'HOME': '/unchanged-home', 'CODEX_HOME': '/unchanged-codex', 'JAVA_TOOL_OPTIONS': 'injection', 'LD_PRELOAD': 'injection'}, clear=True):
            env = check.child_environment(Path('/owned-output'))
            self.assertEqual(env['HOME'], '/unchanged-home')
            self.assertEqual(env['CODEX_HOME'], '/unchanged-codex')
            self.assertEqual(env['TMPDIR'], '/owned-output/tmp')
            self.assertNotIn('JAVA_TOOL_OPTIONS', env)
            self.assertNotIn('LD_PRELOAD', env)

    def test_real_child_file_limit_and_core_limit(self):
        with tempfile.TemporaryDirectory() as d:
            code = '''import importlib.util, os, pathlib, resource, sys
s = importlib.util.spec_from_file_location('check', sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.child_limits(3)
assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
assert resource.getrlimit(resource.RLIMIT_CPU) == (3, 3)
f = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT, 0o600)
os.write(f, b'x' * (m.LOG_CAP * 2))
try:
    os.write(f, b'x')
except OSError:
    pass
else:
    raise AssertionError('file limit did not reject additional byte')
os.close(f)
assert pathlib.Path(sys.argv[2]).stat().st_size == m.LOG_CAP
'''
            subprocess.run([sys.executable, '-B', '-c', code, str(HERE / 'check.py'), str(Path(d) / 'bounded')], check=True, timeout=5, capture_output=True)


if __name__ == '__main__':
    unittest.main()
