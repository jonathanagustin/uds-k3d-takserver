# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise the retained-certificate probe against a local TLS 1.2 mTLS server."""

import importlib.util
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest


SPEC = importlib.util.spec_from_file_location("upgrade_stream", Path(__file__).with_name("upgrade-stream.py"))
stream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stream)


class StreamTests(unittest.TestCase):
    def test_retained_certificate_succeeds_and_missing_certificate_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A temporary self-signed trust anchor is sufficient for this protocol contract.
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem"),
                "-days", "1", "-subj", "/CN=localhost",
            ], check=True, capture_output=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_cert_chain(root / "cert.pem", root / "key.pem")
            context.load_verify_locations(root / "cert.pem")
            outcomes = []
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                listener.settimeout(10)
                port = listener.getsockname()[1]

                def serve():
                    for _ in range(2):
                        raw, _ = listener.accept()
                        with raw:
                            try:
                                with context.wrap_socket(raw, server_side=True) as connection:
                                    outcomes.append(connection.version())
                            except ssl.SSLError:
                                outcomes.append("rejected")

                server = threading.Thread(target=serve, daemon=True)
                server.start()
                stream.connect(port, root / "cert.pem", root / "key.pem")
                with self.assertRaises(ssl.SSLError):
                    stream.connect(port)
                server.join(timeout=15)
                self.assertFalse(server.is_alive())
                self.assertEqual(outcomes, ["TLSv1.2", "rejected"])


if __name__ == "__main__":
    unittest.main()
