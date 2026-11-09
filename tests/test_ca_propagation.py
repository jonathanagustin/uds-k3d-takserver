# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Execute the CA propagation task and verify real X.509 payloads and cleanup."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
FAKE_UDS = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["FAKE_CLUSTER"])
args = sys.argv[4:]
if args[:2] == ["get", "destinationrule.networking.istio.io"]:
    print("istio-tenant-gateway" if "exportTo" in args[-1] else "takserver-web-ca")
elif args[:2] in (["get", "cm"], ["get", "secret"]):
    print((root / "current").read_text())
elif args[:2] == ["patch", "cm"]:
    payload = json.loads(pathlib.Path(args[args.index("--patch-file") + 1]).read_text())["binaryData"]["ca.pem"]
    (root / "current").write_text(payload)
    with (root / "patches").open("a") as out:
        out.write(json.dumps(payload) + "\n")
    if os.environ.get("FAIL_CHANGED_PATCH") and payload != (root / "original").read_text():
        sys.exit(1)
else:
    raise RuntimeError(args)
'''


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
class CAPropagationTests(unittest.TestCase):
    def run_task(self, fail_changed_patch=False):
        tasks = yaml.safe_load((ROOT / "tasks/test.yaml").read_text())["tasks"]
        task = next(t for t in tasks if t["name"] == "cert-rotation")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cert = root / "ca.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(root / "ca.key"), "-out", str(cert),
                "-days", "1", "-subj", "/CN=Propagation test",
            ], check=True, capture_output=True)
            original = base64.b64encode(cert.read_bytes()).decode()
            for name in ("original", "current"):
                (root / name).write_text(original)
            fake = root / "uds"
            fake.write_text(FAKE_UDS)
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", "-c", task["actions"][0]["cmd"]], cwd=ROOT,
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                     "FAKE_CLUSTER": str(root), "TMPDIR": str(root),
                     "FAIL_CHANGED_PATCH": "1" if fail_changed_patch else ""},
                text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 1 if fail_changed_patch else 0, result.stderr)
            patches = [json.loads(line) for line in (root / "patches").read_text().splitlines()]
            self.assertEqual(len(patches), 2)
            self.assertNotEqual(patches[0], original)
            self.assertEqual(patches[1], original)
            self.assertEqual((root / "current").read_text(), original)
            # Both the changed and restored payload must decode as the same
            # certificate. Mutating the first base64 character fails here.
            fingerprints = []
            for payload in patches:
                parsed = subprocess.run(
                    ["openssl", "x509", "-noout", "-fingerprint", "-sha256"],
                    input=base64.b64decode(payload, validate=True), capture_output=True, check=True,
                )
                fingerprints.append(parsed.stdout)
            self.assertEqual(fingerprints[0], fingerprints[1])
            self.assertEqual(list(root.glob("tmp.*")), [])

    def test_changed_and_restored_payloads_remain_valid(self):
        self.run_task()

    def test_failed_patch_still_restores_original_payload(self):
        self.run_task(fail_changed_patch=True)


if __name__ == "__main__":
    unittest.main()
