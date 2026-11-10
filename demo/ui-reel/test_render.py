# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Corrupt or oversized acquisition inputs never reach the media pipeline."""

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("ui_reel", Path(__file__).with_name("render.py"))
REEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REEL)


class Response(io.BytesIO):
    def geturl(self):
        return "https://release-assets.githubusercontent.com/fixture"


class AcquisitionTests(unittest.TestCase):
    def test_render_rejects_corrupt_input_before_any_media_tool_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, output = Path(directory) / "cache", Path(directory) / "output"
            cache.mkdir()
            (cache / "demo-clip-cloudtak-user.mp4").write_bytes(b"changed")
            with patch.object(REEL.subprocess, "check_output") as probe:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    REEL.render(cache, output, offline=True)
                probe.assert_not_called()
            self.assertFalse(output.exists())

    def test_changed_cache_is_rejected_without_fetching_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "clip.mp4").write_bytes(b"changed")
            with patch.object(REEL.urllib.request, "urlopen") as download:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    REEL.acquire({"file": "clip.mp4", "sha256": "0" * 64}, cache)
                download.assert_not_called()
            self.assertEqual((cache / "clip.mp4").read_bytes(), b"changed")

    def test_download_hash_and_size_failures_leave_no_accepted_or_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            item = {"file": "clip.mp4", "sha256": "0" * 64, "url": "https://github.com/fixture"}
            for limit in (1, 100):
                with self.subTest(limit=limit):
                    with patch.object(REEL, "MAX_DOWNLOAD", limit), patch.object(
                            REEL.urllib.request, "urlopen", return_value=Response(b"wrong bytes")):
                        with self.assertRaises(ValueError):
                            REEL.acquire(item, cache)
                    self.assertEqual(list(cache.iterdir()), [])

    def test_verified_download_is_atomic_and_reusable_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            data = b"accepted fixture"
            item = {"file": "clip.mp4", "sha256": hashlib.sha256(data).hexdigest(),
                    "url": "https://github.com/fixture"}
            with patch.object(REEL.urllib.request, "urlopen", return_value=Response(data)):
                path = REEL.acquire(item, cache)
            REEL.verify(path, item["sha256"])
            with patch.object(REEL.urllib.request, "urlopen") as download:
                self.assertEqual(REEL.acquire(item, cache), path)
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
