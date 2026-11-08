# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Run the health server against real public certificates and scrape it."""

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("java") and shutil.which("openssl"), "JDK and OpenSSL required")
class CertificateMetricsTests(unittest.TestCase):
    def test_expiry_updates_and_unreadable_certificates(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            key = work / "key.pem"
            for name, days in (("ca", "40"), ("takserver", "2")):
                subprocess.run([
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(work / f"{name}.pem"),
                    "-days", days, "-subj", f"/CN={name}",
                ], check=True, capture_output=True)

            def not_after(name):
                value = subprocess.check_output([
                    "openssl", "x509", "-in", str(work / f"{name}.pem"), "-noout", "-enddate",
                ], text=True).strip().split("=", 1)[1]
                return int(datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).timestamp())

            ca_expiry, server_expiry = not_after("ca"), not_after("takserver")
            # TAK's PEM includes the CA after the server leaf. The gauge must
            # describe the leaf, whose expiry is sooner than this CA's.
            with (work / "takserver.pem").open("a") as stream:
                stream.write((work / "ca.pem").read_text())
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen([
                "java", "-Xmx24m", str(ROOT / "charts/takserver/files/health/Health.java"),
            ], env={**os.environ, "PORT": str(port), "EXPIRY_CERT_DIR": str(work)},
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                url = f"http://127.0.0.1:{port}/metrics"
                deadline = time.monotonic() + 30
                while True:
                    try:
                        with urlopen(url, timeout=1) as response:
                            body = response.read().decode()
                            self.assertIn("version=0.0.4", response.headers["Content-Type"])
                        break
                    except OSError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            self.fail("Health.java did not start: " + (process.stderr.read() if process.poll() is not None else "timeout"))
                        time.sleep(0.1)
                self.assertIn(f'tak_certificate_not_after_seconds{{certificate="ca"}} {ca_expiry}\n', body)
                self.assertIn(f'tak_certificate_not_after_seconds{{certificate="server"}} {server_expiry}\n', body)
                self.assertIn('tak_certificate_read_success{certificate="server"} 1\n', body)

                (work / "takserver.pem").write_text("not a certificate")
                (work / "ca.pem").unlink()
                with urlopen(url, timeout=2) as response:
                    body = response.read().decode()
                self.assertNotIn('tak_certificate_not_after_seconds{', body)
                self.assertIn('tak_certificate_read_success{certificate="server"} 0\n', body)
                self.assertIn('tak_certificate_read_success{certificate="ca"} 0\n', body)
                # Replacing a projected file is reflected without restart.
                subprocess.run([
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(work / "takserver.pem"),
                    "-days", "1", "-subj", "/CN=replacement",
                ], check=True, capture_output=True)
                with urlopen(url, timeout=2) as response:
                    self.assertIn(f'tak_certificate_not_after_seconds{{certificate="server"}} {not_after("takserver")}\n',
                                  response.read().decode())
            finally:
                process.terminate()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
