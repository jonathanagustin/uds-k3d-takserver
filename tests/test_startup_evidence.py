# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Regression checks for the retained startup qualification evidence."""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'bench/results/startup-pairs-20261114'
SPEC = importlib.util.spec_from_file_location('startup_evidence', ROOT / 'check.py')
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class StartupEvidenceTests(unittest.TestCase):
    def phase(self):
        record = EVIDENCE.decode(EVIDENCE.read(ROOT / 'records/amd64/cold.json'))
        return copy.deepcopy(record['phases']['takserver-api'])

    def test_retained_pairs_and_published_table(self):
        rows, spans = EVIDENCE.verify()
        self.assertEqual(len(rows), 8)
        self.assertEqual(spans, [['amd64', 140, 100], ['arm64', 131, 101]])
        self.assertIn(EVIDENCE.tables(rows, spans), (ROOT / 'README.md').read_text())

    def test_reported_duration_cannot_override_timestamp_evidence(self):
        phase = self.phase()
        phase['jvm_to_log_s'] += 1
        with self.assertRaisesRegex(ValueError, 'reported phase duration differs'):
            EVIDENCE.phase_row('amd64', 'cold', 'takserver-api', phase)

    def test_missing_pull_is_not_zero(self):
        phase = self.phase()
        phase['image_pull_s'] = None
        row = EVIDENCE.phase_row('amd64', 'cold', 'takserver-api', phase)
        self.assertIsNone(row[3])
        self.assertIn('not measured', EVIDENCE.tables([row], []))

    def test_duplicate_keys_nonfinite_and_hash_tampering_rejected(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                EVIDENCE.decode(payload)
        with self.assertRaisesRegex(ValueError, 'hash/size differs'):
            EVIDENCE.read(ROOT / 'records/amd64/cold.json', '0' * 64)


if __name__ == '__main__':
    unittest.main()
