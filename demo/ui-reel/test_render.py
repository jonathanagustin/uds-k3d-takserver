# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Corrupt or oversized acquisition inputs never reach the media pipeline."""

import hashlib
import importlib.util
import io
import json
import zipfile
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


class SceneExportTests(unittest.TestCase):
    def fixture(self, root):
        cache = root / "cache"
        cache.mkdir()
        lock = json.loads(REEL.LOCK.read_text())
        for source in lock["sources"]:
            path = cache / source["file"]
            path.write_bytes(source["file"].encode())
            source["sha256"] = REEL.digest(path)
        font = cache / lock["font"]["file"]
        with zipfile.ZipFile(font, "w") as archive:
            for member in lock["font"]["members"].values():
                archive.writestr(member, "offline font fixture")
        lock["font"]["sha256"] = REEL.digest(font)
        lock_path = root / "lock.json"
        lock_path.write_text(json.dumps(lock))
        return cache, lock, lock_path

    def fake_run(self, command, directory):
        target = Path(command[-1])
        if not target.is_absolute():
            target = directory / target
        target.write_bytes(target.name.encode())

    def fake_probe(self, command, **kwargs):
        if command[-1] == "-version":
            return "offline fixture version\n"
        lengths = {slug + ".mp4": REEL.SCENES[index][3] for index, slug in REEL.SCENE_EXPORTS}
        duration = lengths.get(Path(command[-1]).name, 26)
        return json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264",
                                       "width": 1920, "height": 1080}],
                           "format": {"duration": str(duration)}})

    def test_default_and_opt_in_inventory_and_manifest_binding(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cache, lock, lock_path = self.fixture(root)
                output = root / "reel"
                with patch.object(REEL, "LOCK", lock_path), patch.object(REEL, "run", wraps=self.fake_run) as media, patch.object(
                        REEL.subprocess, "check_output", self.fake_probe), patch.object(
                        REEL.urllib.request, "urlopen") as network:
                    REEL.render(cache, output, offline=True, export=enabled)
                    network.assert_not_called()
                parts = [call.args[0] for call in media.call_args_list
                         if Path(call.args[0][-1]).name.startswith("part")
                         and call.args[0][-1].endswith(".mp4")]
                self.assertEqual(len(parts), 5)
                self.assertTrue(all("RECORDED DEMO FOOTAGE" in command[command.index("-vf") + 1]
                                    for command in parts))
                self.assertEqual({p.name for p in output.iterdir()}, {
                    "uds-takserver-ui-preview.mp4", "poster.jpg", "review-strip.jpg",
                    "Inter-LICENSE.txt", "edit-manifest.json"})
                scenes = root / "reel-scenes"
                self.assertEqual(scenes.exists(), enabled)
                if not enabled:
                    continue
                self.assertEqual(REEL.SCENE_EXPORTS,
                                 ((1, "create-map-marker"), (2, "share-feature"), (4, "shared-marker")))
                self.assertEqual(tuple(REEL.SCENES[index][3] for index, _ in REEL.SCENE_EXPORTS),
                                 (6, 6.5, 6))
                expected = {"Inter-LICENSE.txt"}
                for index, slug in REEL.SCENE_EXPORTS:
                    expected.update(slug + suffix for suffix in (".mp4", ".jpg", ".json"))
                    manifest = json.loads((scenes / (slug + ".json")).read_text())
                    scene = REEL.SCENES[index]
                    self.assertEqual(manifest["scene"]["start_seconds"], scene[2])
                    self.assertEqual(manifest["scene"]["duration_seconds"], scene[3])
                    self.assertEqual(float(manifest["probe"]["format"]["duration"]), scene[3])
                    self.assertEqual(manifest["source_input"], next(
                        item for item in lock["sources"] if item["file"] == scene[1]))
                    self.assertEqual(manifest["font_input"], lock["font"])
                    self.assertEqual(manifest["recipe_sha256"], REEL.digest(Path(REEL.__file__)))
                    self.assertEqual(manifest["lock_sha256"], REEL.digest(lock_path))
                    for item in manifest["outputs"]:
                        path = scenes / item["file"]
                        self.assertEqual(item["sha256"], REEL.digest(path))
                        self.assertEqual(item["bytes"], path.stat().st_size)
                    self.assertIn("Historical footage", manifest["acceptance"])
                self.assertEqual({p.name for p in scenes.iterdir()}, expected)

    def test_opt_in_corrupt_input_and_existing_scene_output_fail_before_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, _, lock_path = self.fixture(root)
            output = root / "reel"
            scenes = root / "reel-scenes"
            scenes.mkdir()
            sentinel = scenes / "keep"
            sentinel.write_bytes(b"keep")
            with patch.object(REEL, "LOCK", lock_path), patch.object(REEL, "run") as media, patch.object(
                    REEL.subprocess, "check_output", self.fake_probe):
                with self.assertRaisesRegex(ValueError, "must be empty"):
                    REEL.render(cache, output, offline=True, export=True)
                (cache / "demo-clip-sync.mp4").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    REEL.render(cache, output, offline=True, export=True)
                media.assert_not_called()
            self.assertEqual(sentinel.read_bytes(), b"keep")
            self.assertFalse(output.exists())

    def test_clip_media_contract_rejects_wrong_duration_or_audio(self):
        for probe in ({"streams": [{"codec_type": "audio"}], "format": {"duration": "6"}},
                      {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920,
                                    "height": 1080}], "format": {"duration": "7"}}):
            with patch.object(REEL.subprocess, "check_output", return_value=json.dumps(probe)):
                with self.assertRaises(ValueError):
                    REEL.probe_video(Path("clip.mp4"), 6)


if __name__ == "__main__":
    unittest.main()
