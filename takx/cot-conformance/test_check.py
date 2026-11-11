# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
