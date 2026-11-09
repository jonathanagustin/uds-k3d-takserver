# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_compliance", ROOT / ".github/scripts/check-compliance.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
IDENTIFIER = "d94eeeb3-a4bf-4efb-a149-64e9987053d5"


class ComplianceMappings(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.controls = self.root / "compliance/controls/AC"
        self.mappings = self.root / "compliance/mappings/AC"
        self.controls.mkdir(parents=True)
        self.mappings.mkdir(parents=True)
        (self.controls / "AC-3.yaml").write_text(yaml.safe_dump({
            "id": "AC-3", "title": "Access enforcement", "family": "AC",
            "implementation_status": "Partially Implemented",
            "control_implementation_narrative": "A scoped implementation.",
            "assessment_procedures": "Run the linked checks.",
            "links": [{"href": "https://example.com/test", "rel": "evidence"}],
        }))
        self.mapping = {"uuid": IDENTIFIER, "control_id": "AC-3", "status": "planned",
                        "justification": "Proposed source evidence.",
                        "source_entries": [{"location": "source.yaml"}]}
        self.write_mapping()
        self.source = self.root / "source.yaml"
        self.source.write_text(self.block(IDENTIFIER))

    def block(self, identifier):
        return f"# @lulaStart {identifier}\nvalue: true\n# @lulaEnd {identifier}\n"

    def write_mapping(self):
        (self.mappings / "AC-3-mappings.yaml").write_text(yaml.safe_dump([self.mapping]))

    def test_valid_mapping_and_untracked_source_pass(self):
        self.assertEqual(CHECKER.check(self.root), [])

    def test_missing_end_fails(self):
        self.source.write_text(self.block(IDENTIFIER).split("# @lulaEnd")[0])
        self.assertTrue(any("missing end marker" in error for error in CHECKER.check(self.root)))

    def test_unknown_marker_in_an_unmapped_file_fails(self):
        (self.root / "other.yaml").write_text(self.block("11111111-1111-4111-8111-111111111111"))
        self.assertTrue(any("unknown marker UUID" in error for error in CHECKER.check(self.root)))

    def test_missing_source_fails(self):
        self.source.unlink()
        self.assertTrue(any("mapped file does not exist" in error for error in CHECKER.check(self.root)))

    def test_source_outside_repository_is_rejected(self):
        self.mapping["source_entries"] = [{"location": "../source.yaml"}]
        self.write_mapping()
        self.assertTrue(any("repository-relative" in error for error in CHECKER.check(self.root)))

    def test_known_uuid_in_the_wrong_file_fails(self):
        (self.root / "other.yaml").write_text(self.block(IDENTIFIER))
        self.assertTrue(any("not mapped to this file" in error for error in CHECKER.check(self.root)))

    def test_duplicate_uuid_and_unknown_control_are_rejected(self):
        self.mapping["control_id"] = "AC-999"
        self.write_mapping()
        (self.mappings / "copy-mappings.yaml").write_text(yaml.safe_dump([self.mapping]))
        errors = CHECKER.check(self.root)
        self.assertTrue(any("duplicate mapping UUID" in error for error in errors))
        self.assertTrue(any("unknown control" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
