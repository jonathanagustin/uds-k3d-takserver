# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Source integrity, deterministic packaging and actual JDK resource lookups."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gdal_data_build", ROOT / "build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
ARCHIVE = os.environ.get("GDAL_DATA_ARCHIVE")


class IntegrityGuardTests(unittest.TestCase):
    def test_unverified_source_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "unverified.tar.gz", root / "output"
            source.write_bytes(b"not the locked source archive")
            with self.assertRaisesRegex(ValueError, "source archive size mismatch"):
                BUILD.build(source, output)
            self.assertFalse(output.exists())

    def test_same_size_dummy_fails_hash_check_before_tar_parsing_or_output(self):
        lock = json.loads(BUILD.LOCK.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "same-size.tar.gz", root / "output"
            # A sparse zero-filled file exercises the real hash over exactly the
            # locked input size without allocating or downloading archive bytes.
            with source.open("wb") as stream:
                stream.truncate(lock["archive"]["bytes"])
            self.assertEqual(source.stat().st_size, lock["archive"]["bytes"])
            with patch.object(BUILD.tarfile, "open") as parse:
                with self.assertRaisesRegex(ValueError, "source archive SHA-256 mismatch"):
                    BUILD.build(source, output)
                parse.assert_not_called()
            self.assertFalse(output.exists())


@unittest.skipUnless(ARCHIVE, "set GDAL_DATA_ARCHIVE to the locked public source archive")
class PublicSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.archive = Path(ARCHIVE)
        cls.lock = json.loads(BUILD.LOCK.read_text())
        cls.first = BUILD.build(cls.archive, cls.root / "first")
        cls.jar = cls.root / "first" / cls.first["artifact"]["file"]

    def test_changed_same_size_archive_fails_before_packaging(self):
        source = self.root / "changed.tar.gz"
        data = bytearray(self.archive.read_bytes())
        data[len(data) // 2] ^= 1
        source.write_bytes(data)
        output = self.root / "rejected"
        with self.assertRaisesRegex(ValueError, "source archive SHA-256 mismatch"):
            BUILD.build(source, output)
        self.assertFalse(output.exists())

    def test_two_clean_builds_are_identical_and_preserve_all_source_data_and_license(self):
        second = BUILD.build(self.archive, self.root / "second")
        self.assertEqual(self.first, second)
        self.assertEqual(self.jar.read_bytes(), (self.root / "second" / second["artifact"]["file"]).read_bytes())
        with zipfile.ZipFile(self.jar) as jar:
            names = jar.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(len([name for name in names if name.startswith("gdal/data/")]), 93)
            for name, expected in self.lock["resources"].items():
                self.assertEqual(hashlib.sha256(jar.read("gdal/data/" + name)).hexdigest(), expected["sha256"])
            self.assertEqual(hashlib.sha256(jar.read("META-INF/licenses/GDAL-LICENSE.txt")).hexdigest(),
                             self.lock["source_notices"]["./gdal/LICENSE.TXT"]["sha256"])
            for entry in jar.infolist():
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)

    def test_jdk_classloader_reads_all_locked_resources_from_the_project_jar(self):
        expected = {name: entry["sha256"] for name, entry in self.lock["resources"].items()}
        index = "\n".join(sorted([*expected, "gdaldata.files"])) + "\n"
        expected["gdaldata.files"] = hashlib.sha256(index.encode("ascii")).hexdigest()
        hashes = self.root / "expected.tsv"
        hashes.write_text("".join(name + "\t" + digest + "\n" for name, digest in sorted(expected.items())))
        classes = self.root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "11", "-d", str(classes),
                        str(ROOT / "ResourceLookupProbe.java")], check=True, timeout=30)
        result = subprocess.run(["java", "-cp", os.pathsep.join([str(classes), str(self.jar)]),
                                 "ResourceLookupProbe", str(hashes)], check=True, timeout=30,
                                capture_output=True, text=True)
        self.assertIn("PASS 93 JDK classloader resource lookups", result.stdout)


if __name__ == "__main__":
    unittest.main()
