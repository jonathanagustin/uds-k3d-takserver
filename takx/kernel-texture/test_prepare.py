# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline source-boundary guards; no compiler, network or native execution."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("texture_prepare", Path(__file__).with_name("prepare.py"))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)

class SourceGuards(unittest.TestCase):
    def test_committed_patch_binding(self):
        lock, patch = p.load_contract()
        self.assertEqual(hashlib.sha256(patch).hexdigest(), lock["patch_sha256"])
        self.assertGreater(len(lock["files"]), 1)

    def test_source_and_postimage_are_distinct_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "takkernel/engine/src/Style.h"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"before")
            files = {"takkernel/engine/src/Style.h": {"before_sha256": p.digest(b"before"), "after_sha256": p.digest(b"after")}}
            p.verify_files(root, files, "before_sha256")
            with self.assertRaises(ValueError):
                p.verify_files(root, files, "after_sha256")
            source.write_bytes(b"after")
            p.verify_files(root, files, "after_sha256")
            with self.assertRaises(ValueError):
                p.verify_files(root, files, "before_sha256")

    def test_linked_file_and_parent_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_bytes(b"before")
            target = root / "takkernel/engine/src/Style.h"
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)
            files = {"takkernel/engine/src/Style.h": {"before_sha256": p.digest(b"before")}}
            with self.assertRaises(ValueError):
                p.verify_files(root, files, "before_sha256")
            target.unlink()
            target.parent.rmdir()
            target.parent.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                p.verify_files(root, files, "before_sha256")

    def test_new_file_must_be_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "takkernel/engine/src/new.h"
            target.parent.mkdir(parents=True)
            files = {"takkernel/engine/src/new.h": {"before_sha256": None}}
            p.verify_files(root, files, "before_sha256")
            target.write_bytes(b"existing")
            with self.assertRaises(ValueError):
                p.verify_files(root, files, "before_sha256")

    def test_traversal_and_other_component_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ["../outside", "/takkernel/engine/src/a", "takkernel/engine/src/../../a", "commoncommo/src/a", "takkernel\\engine\\src\\a"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    p.source_path(Path(directory), name)

    def test_oversized_source_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "file"
            source.write_bytes(b"12345")
            with self.assertRaises(ValueError):
                p.regular_bytes(source, limit=4)

if __name__ == "__main__":
    unittest.main()
