# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""issue-health-cert.sh issues the tak-health client certificate once.

Each case runs the script against a local HTTPS stand-in for the Kubernetes
API. Needs bash, curl, and openssl. No cluster.
"""

import base64
import json
import os
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "charts" / "takserver" / "files" / "scripts" / "issue-health-cert.sh"
PREREQS = ROOT / "charts" / "takserver" / "templates" / "prereqs.yaml"
CAPASS = "test-ca-pass"
NS = "takserver"


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def make_ca(d: Path, name: str):
    key, pem = d / f"{name}.key", d / f"{name}.pem"
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-days", "30",
         "-subj", f"/CN={name}", "-keyout", str(key), "-out", str(pem),
         "-passout", f"pass:{CAPASS}"])
    return key, pem


def make_client(d: Path, ca_key: Path, ca_pem: Path, days: int) -> Path:
    key, csr, pem = d / "old.key", d / "old.csr", d / "old.pem"
    run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=tak-health",
         "-keyout", str(key), "-out", str(csr)])
    run(["openssl", "x509", "-req", "-in", str(csr), "-days", str(days), "-CA", str(ca_pem),
         "-CAkey", str(ca_key), "-passin", f"pass:{CAPASS}", "-set_serial", "1", "-out", str(pem)])
    return pem


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


class FakeApi:
    """Serves cert-migration and one Secret, and records writes."""

    def __init__(self, tls_dir: Path, ca_pem: Path, secret=None):
        self.configmap = {"binaryData": {"ca.pem": b64(ca_pem)}}
        self.secret = secret
        self.writes = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, code, body):
                data = json.dumps(body, indent=2).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                base = f"/api/v1/namespaces/{NS}"
                if self.path == f"{base}/configmaps/cert-migration":
                    self.reply(200, api.configmap)
                elif self.path == f"{base}/secrets/tak-health-client" and api.secret:
                    self.reply(200, {"data": api.secret})
                else:
                    self.reply(404, {"kind": "Status"})

            def write(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.writes.append((self.command, self.path, body))
                api.secret = body["data"]
                self.reply(201 if self.command == "POST" else 200, body)

            do_POST = write
            do_PUT = write

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tls_dir / "server.pem", tls_dir / "server.key")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"https://127.0.0.1:{self.server.server_address[1]}"


class IssueHealthCertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.sa = self.d / "sa"
        self.sa.mkdir()
        (self.sa / "namespace").write_text(NS)
        (self.sa / "token").write_text("token")
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
             "-keyout", str(self.d / "server.key"), "-out", str(self.d / "server.pem")])
        (self.sa / "ca.crt").write_bytes((self.d / "server.pem").read_bytes())
        self.ca_key, self.ca_pem = make_ca(self.d, "ca")

    def tearDown(self):
        self.tmp.cleanup()

    def issue(self, api: FakeApi):
        env = dict(os.environ, CAPASS=CAPASS, SA_DIR=str(self.sa), KUBE_API=api.url,
                   CA_KEY_FILE=str(self.ca_key))
        try:
            return run(["bash", str(SCRIPT)], env=env, timeout=60)
        finally:
            api.server.shutdown()

    def assert_issued(self, data):
        for name in ("ca.pem", "client.pem", "client.key"):
            (self.d / f"got-{name}").write_bytes(base64.b64decode(data[name]))
        self.assertEqual((self.d / "got-ca.pem").read_bytes(), self.ca_pem.read_bytes())
        run(["openssl", "verify", "-CAfile", str(self.ca_pem), str(self.d / "got-client.pem")])
        text = run(["openssl", "x509", "-in", str(self.d / "got-client.pem"), "-noout",
                    "-subject", "-ext", "extendedKeyUsage,basicConstraints"]).stdout
        self.assertIn("CN=tak-health", text.replace(" = ", "="))
        self.assertIn("TLS Web Client Authentication", text)
        self.assertNotIn("Server Authentication", text)
        self.assertIn("CA:FALSE", text)
        # The key is not encrypted, so the pod needs no keystore password.
        key = (self.d / "got-client.key").read_text()
        self.assertNotIn("ENCRYPTED", key)
        run(["openssl", "pkey", "-in", str(self.d / "got-client.key"), "-noout",
             "-passin", "pass:"])

    def test_missing_secret_is_created(self):
        api = FakeApi(self.d, self.ca_pem)
        out = self.issue(api)
        self.assertEqual([w[0] for w in api.writes], ["POST"])
        method, path, body = api.writes[0]
        self.assertEqual(path, f"/api/v1/namespaces/{NS}/secrets")
        self.assertEqual(body["metadata"]["name"], "tak-health-client")
        self.assert_issued(body["data"])
        self.assertNotIn(CAPASS, out.stdout + out.stderr)

    def test_current_certificate_is_kept(self):
        pem = make_client(self.d, self.ca_key, self.ca_pem, days=365)
        secret = {"ca.pem": b64(self.ca_pem), "client.pem": b64(pem), "client.key": "eA=="}
        api = FakeApi(self.d, self.ca_pem, secret=dict(secret))
        out = self.issue(api)
        self.assertEqual(api.writes, [])
        self.assertIn("already has a current client certificate", out.stdout)

    def test_certificate_from_another_ca_is_replaced(self):
        other_key, other_pem = make_ca(self.d, "other")
        pem = make_client(self.d, other_key, other_pem, days=365)
        secret = {"ca.pem": b64(other_pem), "client.pem": b64(pem), "client.key": "eA=="}
        api = FakeApi(self.d, self.ca_pem, secret=secret)
        self.issue(api)
        self.assertEqual([(w[0], w[1]) for w in api.writes],
                         [("PUT", f"/api/v1/namespaces/{NS}/secrets/tak-health-client")])
        self.assert_issued(api.writes[0][2]["data"])

    def test_certificate_near_expiry_is_replaced(self):
        pem = make_client(self.d, self.ca_key, self.ca_pem, days=10)
        secret = {"ca.pem": b64(self.ca_pem), "client.pem": b64(pem), "client.key": "eA=="}
        api = FakeApi(self.d, self.ca_pem, secret=secret)
        self.issue(api)
        self.assertEqual([w[0] for w in api.writes], ["PUT"])
        self.assert_issued(api.writes[0][2]["data"])

    def test_cert_job_issues_before_the_ca_key_moves(self):
        text = PREREQS.read_text()
        issue = text.index("files/scripts/issue-health-cert.sh")
        move = text.index("files/scripts/move-ca-key.sh")
        self.assertLess(issue, move)
        # The script exits 0 when the Secret is current. It is inlined, so
        # that exit has to stay inside a subshell.
        self.assertEqual(text[:issue].splitlines()[-2].strip(), "(")
        self.assertIn('"tak-health-client"', text)


if __name__ == "__main__":
    unittest.main()
