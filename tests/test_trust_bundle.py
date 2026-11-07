# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Verify rendered trust mounts and Node TLS with two independent CAs."""

import http.server
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(chart):
    result = subprocess.run(["helm", "template", chart, str(ROOT / "charts" / chart)],
                            text=True, capture_output=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@unittest.skipUnless(shutil.which("helm"), "helm CLI is not installed")
class TrustBundleChartTests(unittest.TestCase):
    def test_both_bundles_reload_only_their_consumers(self):
        for chart, selector in (("takserver", "uds.dev/oidc-reload=takserver"),
                                ("cloudtak", "app=cloudtak")):
            with self.subTest(chart=chart):
                package = next(d for d in render(chart) if d["kind"] == "Package")
                config = package["spec"]["caBundle"]["configMap"]
                self.assertEqual(config["name"], "uds-trust-bundle")
                self.assertEqual(config["key"], "ca-bundle.pem")
                self.assertEqual(config["labels"], {"uds.dev/pod-reload": "true"})
                self.assertEqual(config["annotations"], {"uds.dev/pod-reload-selector": selector})

    def test_cloudtak_reads_the_merged_file_without_admin_key_access(self):
        deployment = next(d for d in render("cloudtak")
                          if d["kind"] == "Deployment" and d["metadata"]["name"] == "cloudtak")
        spec = deployment["spec"]["template"]["spec"]
        bundle = next(v for v in spec["volumes"] if v["name"] == "uds-trust")
        self.assertEqual(bundle["configMap"], {"name": "uds-trust-bundle", "optional": True})
        init = spec["initContainers"][0]
        self.assertEqual(init["name"], "merge-trust")
        self.assertEqual(init["command"], ["/bin/sh", "-ec"])
        self.assertNotIn("tak-admin", {m["name"] for m in init["volumeMounts"]})
        for container in spec["containers"][:2]:
            env = {e["name"]: e.get("value") for e in container["env"]}
            self.assertEqual(env["NODE_EXTRA_CA_CERTS"], "/var/run/combined-trust/ca-bundle.pem")
            mount = next(m for m in container["volumeMounts"] if m["name"] == "combined-trust")
            self.assertTrue(mount["readOnly"])
            self.assertNotIn("tak-admin", {m["name"] for m in container["volumeMounts"]})
        self.assertEqual(init["args"][0].strip(),
                         (ROOT / "charts/cloudtak/files/merge-trust.sh").read_text().strip())


class QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


@unittest.skipUnless(shutil.which("node") and shutil.which("openssl"), "Node and OpenSSL are required")
class TrustBundleTLS(unittest.TestCase):
    def test_node_trusts_both_cas_and_slim_core_still_works(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            servers = []
            try:
                for name in ("tak", "core"):
                    cert, key = root / f"{name}.pem", root / f"{name}.key"
                    subprocess.run([
                        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", f"/CN={name}", "-addext", "subjectAltName=DNS:localhost",
                    ], check=True, capture_output=True)
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(cert, key)
                    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
                    server.socket = context.wrap_socket(server.socket, server_side=True)
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                    servers.append(server)
                merge = ROOT / "charts/cloudtak/files/merge-trust.sh"
                output = root / "combined.pem"
                request = """const https = require('node:https');
https.get({host: '127.0.0.1', servername: 'localhost', port: +process.argv[1]},
  response => { response.resume(); process.exitCode = response.statusCode === 200 ? 0 : 1; })
  .on('error', () => { process.exitCode = 1; });"""

                def connects(server):
                    return subprocess.run(
                        ["node", "-e", request, str(server.server_port)],
                        env={**os.environ, "NODE_EXTRA_CA_CERTS": str(output)},
                        capture_output=True, timeout=10,
                    ).returncode == 0

                def assemble(bundle):
                    if output.exists():
                        output.chmod(0o644)
                    subprocess.run(["sh", str(merge), str(root / "tak.pem"),
                                    str(bundle), str(output)], check=True)

                assemble(root / "core.pem")
                self.assertTrue(all(connects(server) for server in servers))
                for bundle in (root / "absent.pem", root / "empty.pem"):
                    if bundle.name == "empty.pem":
                        bundle.touch()
                    assemble(bundle)
                    self.assertTrue(connects(servers[0]))
                    self.assertFalse(connects(servers[1]))
                # A missing TAK CA must fail the init container.
                result = subprocess.run(["sh", str(merge), str(root / "missing.pem"),
                                         str(root / "core.pem"), str(output)])
                self.assertNotEqual(result.returncode, 0)
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
