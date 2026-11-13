# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Regression for a genuine bound Boost header filename; no native/validation execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('finalization_guards', Path(__file__).with_name('finalization_validation.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class LiteralEvidenceGuards(unittest.TestCase):
    def test_header_space_is_hashed_without_becoming_a_pkg_config_token(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'collection_size_type copy.hpp'
            path.write_bytes(b'owned literal evidence fixture')
            expected = f.sha(path)
            self.assertEqual(f.checked_regular_evidence(path, expected), path)
            with self.assertRaisesRegex(ValueError, 'pkg-config path'):
                f.kml.checked(path, expected)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA differs'):
                f.checked_regular_evidence(path, expected)

    def test_literal_evidence_still_rejects_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'actual.hpp'
            target.write_bytes(b'owned evidence fixture')
            alias = root / 'alias copy.hpp'
            alias.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'regular evidence'):
                f.checked_regular_evidence(alias, f.sha(target))


if __name__ == '__main__':
    unittest.main()
