# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import tempfile
import stat
import os
import subprocess
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("scenario", Path(__file__).resolve().parents[1] / "atak/scenarios/android-interoperability.py")
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


class ScenarioInputTest(unittest.TestCase):
    def package(self, directory, uid="synthetic-android-test", lat="0", extra=None):
        path = Path(directory) / "fixture.dpk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("MANIFEST/manifest.xml", '<MissionPackageManifest version="2"><Contents><Content zipEntry="cot/point.cot"><Parameter name="isCoT" value="true"/></Content><Content zipEntry="files/README.txt"/></Contents></MissionPackageManifest>')
            archive.writestr("files/README.txt", "Synthetic TEST attachment")
            archive.writestr("cot/point.cot", f'<event uid="{uid}" type="a-f-G-U-C"><point lat="{lat}" lon="0"/><detail><contact callsign="TEST MARKER"/></detail></event>')
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
            with patch("sys.argv", ["scenario", "--mission-package", str(package), "--output", str(Path(directory) / "out")]), patch.object(scenario, "run_bounded", side_effect=AssertionError("offline must not execute")):
                scenario.main()
            self.assertIn('"execution": "not-run"', (Path(directory) / "out/receipt.json").read_text())


    def test_reject_cross_platform_and_special_entries(self):
        for name, mode, compression in (
            ("C:/evil", 0, zipfile.ZIP_STORED),
            ("a\\evil", 0, zipfile.ZIP_STORED),
            ("a/./evil", 0, zipfile.ZIP_STORED),
            ("a//evil", 0, zipfile.ZIP_STORED),
            ("control\x01", 0, zipfile.ZIP_STORED),
            ("link", stat.S_IFLNK | 0o777, zipfile.ZIP_STORED),
            ("fifo", stat.S_IFIFO | 0o600, zipfile.ZIP_STORED),
            ("bzip", 0, zipfile.ZIP_BZIP2),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self.package(directory)
                with zipfile.ZipFile(path, "a") as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = mode << 16
                    entry.compress_type = compression
                    archive.writestr(entry, "not accepted")
                with self.assertRaises(ValueError):
                    scenario.inspect_package(path)

    def test_reject_raw_nul_and_encryption_flags(self):
        for mutation in ("nul", "encrypted"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                path = self.package(directory)
                data = bytearray(path.read_bytes())
                if mutation == "nul":
                    data = data.replace(b"cot/point.cot", b"cot/point\x00cot")
                else:
                    # Set encryption in the actual central directory, without
                    # attempting to create or decrypt an encrypted fixture.
                    index = data.index(b"PK\x01\x02")
                    data[index + 8] |= 1
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    scenario.inspect_package(path)

    def test_reject_missing_manifest_references(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.package(directory)
            # Rebuild valid ZIP CRCs while leaving a deliberately absent ref.
            with zipfile.ZipFile(path) as archive:
                members = {n: archive.read(n) for n in archive.namelist()}
            members["MANIFEST/manifest.xml"] = members["MANIFEST/manifest.xml"].replace(b"README.txt", b"MISSING.tx")
            with zipfile.ZipFile(path, "w") as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)
            with self.assertRaises(ValueError):
                scenario.inspect_package(path)

    def test_wrapper_cleans_on_copy_failure_and_rejects_untrusted_temp(self):
        for remote, cleanup in (("/tmp/android-scenario.Abc123", True), ("/tmp/unrelated", False)):
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = self.package(directory)
                uds = root / "uds"
                uds.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\ncase "$*" in *mktemp*) printf "%s\\n" "$REMOTE";; *" cp "*) exit 1;; esac\n')
                uds.chmod(0o755)
                env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"], CALL_LOG=str(root / "calls"), REMOTE=remote)
                result = subprocess.run(["bash", "demo/atak-adb.sh", "scenario", str(package), str(root / "out")], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual("rm -rf --" in (root / "calls").read_text(), cleanup)

    def test_real_device_protocol_mock_only_stages_and_never_claims_import(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            output = Path(directory) / "out"
            def protocol(command, **kwargs):
                if command[-1] == "get-state":
                    payload = b"device\n"
                elif "path" in command:
                    payload = b"package:/data/app/test/base.apk\n"
                elif "cat" in command:
                    payload = b"<hierarchy/>"
                else:
                    payload = b""
                return payload
            with patch("sys.argv", ["scenario", "--mission-package", str(package), "--device", "mock-device", "--output", str(output)]), patch.object(scenario, "run_bounded", side_effect=protocol) as run:
                scenario.main()
            receipt = __import__("json").loads((output / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "staged-for-manual-import")
            calls = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any("push" in call for call in calls))
            self.assertFalse(any("monkey" in call or "am" in call for call in calls))

    def test_device_failure_preserves_typed_receipt(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            output = Path(directory) / "out"
            with patch("sys.argv", ["scenario", "--mission-package", str(package), "--device", "mock-device", "--output", str(output)]), patch.object(scenario, "run_bounded", side_effect=subprocess.TimeoutExpired("adb", 45)):
                with self.assertRaises(SystemExit):
                    scenario.main()
            receipt = __import__("json").loads((output / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["error_type"], "TimeoutExpired")


    def test_explicit_import_uri_protocol_mock_requires_hash_and_dispatch_ack(self):
        from unittest.mock import patch
        for mismatch, ack in ((False, b"Status: ok\n"), (True, b"Status: ok\n"), (False, b"Error: denied\n")):
            with self.subTest(mismatch=mismatch, ack=ack), tempfile.TemporaryDirectory() as directory:
                package = self.package(directory)
                output = Path(directory) / "out"
                def protocol(command, **kwargs):
                    if command[-1] == "get-state": return b"device\n"
                    if "path" in command: return b"package:/test.apk\n"
                    if "content" in command: return b"wrong" if mismatch else package.read_bytes()
                    if "am" in command: return ack
                    return b""
                argv = ["scenario", "--mission-package", str(package), "--device", "mock-device", "--import-content-uri", "content://media/external/file/123", "--output", str(output)]
                with patch("sys.argv", argv), patch.object(scenario, "run_bounded", side_effect=protocol) as run:
                    if mismatch or b"Status: ok" not in ack:
                        with self.assertRaises(SystemExit): scenario.main()
                    else:
                        scenario.main()
                receipt = __import__("json").loads((output / "receipt.json").read_text())
                self.assertEqual(receipt["status"], "failed" if mismatch or b"Status: ok" not in ack else "android-import-activity-dispatched-unverified")
                commands = [call.args[0] for call in run.call_args_list]
                if mismatch: self.assertFalse(any("am" in c for c in commands))
                elif b"Status: ok" in ack:
                    dispatch = next(c for c in commands if "am" in c)
                    self.assertIn("android.intent.extra.STREAM", dispatch)
                    self.assertIn("android.intent.action.SEND", dispatch)

    def test_bounded_real_subprocess_guards(self):
        import sys
        with self.assertRaises(ValueError):
            scenario.run_bounded([sys.executable, "-c", "print('x'*1024)"], limit=16)
        with self.assertRaises(TimeoutError):
            scenario.run_bounded([sys.executable, "-c", "import time;time.sleep(.2)"], timeout=.02)
        self.assertEqual(scenario.run_bounded([sys.executable, "-c", "print('ok')"]), b"ok\n")


peer_spec = importlib.util.spec_from_file_location("peer", Path(__file__).resolve().parents[1] / "atak/scenarios/observe-peer.py")
peer = importlib.util.module_from_spec(peer_spec)
peer_spec.loader.exec_module(peer)


class PeerObservationTest(unittest.TestCase):
    # Explicit socket protocol fixtures, never a live peer qualification.
    markers = [{"uid": "synthetic-android-test", "type": "a-f-G-U-C", "lat": 0.0, "lon": 0.0, "callsign": "TEST MARKER"}]
    event = b'<event uid="synthetic-android-test" type="a-f-G-U-C"><point lat="0" lon="0"/><detail><contact callsign="TEST MARKER"/></detail></event>'

    class Stream:
        def __init__(self, chunks): self.chunks = iter(chunks)
        def settimeout(self, timeout): pass
        def recv(self, size): return next(self.chunks, b"")

    def test_fragmented_received_marker(self):
        import time
        result = peer.observe(self.Stream([b'<?xml version="1.0"?>' + self.event[:40], self.event[40:]]), self.markers, time.monotonic() + 1)
        self.assertEqual(result["received_matching_uids"], ["synthetic-android-test"])

    def test_wrong_point_type_and_receive_budget_fail(self):
        import time
        for payload in (self.event.replace(b'lat="0"', b'lat="1"'), self.event.replace(b'a-f-G-U-C', b'a-h-G-U-C'), b'x' * (peer.LIMIT + 1), b'<!DOCTYPE x>' + self.event):
            with self.subTest(payload=payload[:30]), self.assertRaises(ValueError):
                peer.observe(self.Stream([payload]), self.markers, time.monotonic() + 1)

    def test_no_observation_is_not_success(self):
        import time
        with self.assertRaises(RuntimeError): peer.observe(self.Stream([]), self.markers, time.monotonic() + 1)
        with self.assertRaises(TimeoutError): peer.observe(self.Stream([]), self.markers, time.monotonic() - 1)
