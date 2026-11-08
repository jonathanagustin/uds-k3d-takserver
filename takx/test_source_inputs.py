# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Input guards use tiny Git/archive fixtures, not fabricated SDK classes."""

import copy
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import source_inputs


class SourceGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "source"
        self.source.mkdir()
        header = self.source / "commoncommo/core/include/commoversion.h"
        header.parent.mkdir(parents=True)
        header.write_text("#define COMMO_MAJOR 1\n#define COMMO_MINOR 17\n#define COMMO_PATCH 2\n")
        self.code = self.source / "commoncommo/source.cpp"
        self.code.write_text("// tracked source fixture\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=0+fixture@users.noreply.github.com",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.data = b"locked source archive fixture\n"
        self.entry = {
            "path": "takthirdparty/distfiles/source.tar.gz", "bytes": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "url": f"https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/{self.revision}/takthirdparty/distfiles/source.tar.gz",
        }
        self.lock = {"atak_source": {"revision": self.revision}, "commoncommo_version": "1.17.2", "archives": [self.entry]}
        self.cache = Path(self.temporary.name) / "cache"
        self.destination = self.source / self.entry["path"]

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True, stderr=subprocess.DEVNULL)

    def pointer(self):
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{self.entry['sha256']}\nsize {self.entry['bytes']}\n")

    def test_wrong_revision_is_rejected(self):
        lock = copy.deepcopy(self.lock)
        lock["atak_source"]["revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "revision"):
            source_inputs.verify_source(self.source, lock)

    def test_modified_tracked_code_is_rejected(self):
        self.code.write_text("// modified source\n")
        with self.assertRaises(subprocess.CalledProcessError):
            source_inputs.verify_source(self.source, self.lock)

    def test_untracked_source_is_rejected_but_ignored_outputs_are_allowed(self):
        extra = self.source / "commoncommo/unreviewed.cpp"
        extra.write_text("// untracked build input\n")
        with self.assertRaisesRegex(ValueError, "Untracked"):
            source_inputs.verify_source(self.source, self.lock)
        extra.unlink()
        (self.source / ".git/info/exclude").write_text("commoncommo/generated/\n")
        generated = self.source / "commoncommo/generated/output.class"
        generated.parent.mkdir()
        generated.write_bytes(b"generated fixture")
        source_inputs.verify_source(self.source, self.lock)

    def test_transitive_native_outputs_are_part_of_cache_integrity(self):
        output = Path(self.temporary.name) / "output"
        for name in (*source_inputs.ARTIFACTS, "lib/libcurl.a", "lib/ossl-modules/legacy.so"):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"cache-integrity fixture")
        before = source_inputs.artifact_state(output, "key")
        self.assertIn("lib/ossl-modules/legacy.so", before["artifacts"])
        (output / "lib/libcurl.a").write_bytes(b"altered transitive output")
        self.assertNotEqual(before, source_inputs.artifact_state(output, "key"))

    def test_version_cannot_be_relabeled(self):
        lock = copy.deepcopy(self.lock)
        lock["commoncommo_version"] = "1.22.3"
        with self.assertRaisesRegex(ValueError, "version"):
            source_inputs.verify_source(self.source, lock)

    def test_corrupt_existing_archive_fails_without_network_or_overwrite(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"x" * len(self.data))
        with patch.object(source_inputs.urllib.request, "urlopen") as network:
            with self.assertRaisesRegex(ValueError, "mismatch"):
                source_inputs.materialize(self.source, self.cache, self.lock)
            network.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b"x" * len(self.data))

    def test_verified_cache_materializes_lfs_pointer_offline(self):
        self.pointer()
        self.cache.mkdir()
        (self.cache / self.entry["sha256"]).write_bytes(self.data)
        with patch.object(source_inputs.urllib.request, "urlopen") as network:
            source_inputs.materialize(self.source, self.cache, self.lock, offline=True)
            network.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), self.data)

    def test_bad_download_is_not_cached_or_materialized(self):
        self.pointer()
        original = self.destination.read_bytes()
        with patch.object(source_inputs.urllib.request, "urlopen", return_value=io.BytesIO(b"x" * len(self.data))):
            with self.assertRaisesRegex(ValueError, "mismatch"):
                source_inputs.materialize(self.source, self.cache, self.lock)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_non_official_url_is_rejected_before_network(self):
        lock = copy.deepcopy(self.lock)
        lock["archives"][0]["url"] = "https://example.invalid/source.tar.gz"
        with patch.object(source_inputs.urllib.request, "urlopen") as network:
            with self.assertRaisesRegex(ValueError, "official"):
                source_inputs.materialize(self.source, self.cache, lock)
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
