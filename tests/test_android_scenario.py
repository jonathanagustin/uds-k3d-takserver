# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("scenario", Path(__file__).resolve().parents[1] / "atak/scenarios/android-interoperability.py")
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


class ScenarioInputTest(unittest.TestCase):
    def package(self, directory, uid="synthetic-android-test", lat="0", extra=None):
        path = Path(directory) / "fixture.dpk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("MANIFEST/manifest.xml", '<MissionPackageManifest version="2"/>')
            archive.writestr("cot/point.cot", f'<event uid="{uid}"><point lat="{lat}" lon="0"/><detail><contact callsign="TEST MARKER"/></detail></event>')
            if extra:
                archive.writestr(extra, "unsafe")
        return path

    def test_hash_bound_synthetic_map_point(self):
        with tempfile.TemporaryDirectory() as directory:
            result = scenario.inspect_package(self.package(directory))
            self.assertEqual(result["markers"][0]["uid"], "synthetic-android-test")
            self.assertEqual(len(result["package_sha256"]), 64)

    def test_reject_real_uid_bad_coordinates_and_traversal(self):
        for kwargs in ({"uid": "real-device"}, {"lat": "91"}, {"extra": "../escape"}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    scenario.inspect_package(self.package(directory, **kwargs))

    def test_offline_never_invokes_adb(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            with patch("sys.argv", ["scenario", "--mission-package", str(package), "--output", str(Path(directory) / "out")]), patch.object(scenario.subprocess, "run", side_effect=AssertionError("offline must not execute")):
                scenario.main()
            self.assertIn('"execution": "not-run"', (Path(directory) / "out/receipt.json").read_text())
