# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The CA key field can be removed from a ConfigMap body without a cluster.

api_curl retries a dropped handshake and still returns an HTTP 409, which
the cert hooks treat as "already exists"."""

import socket
import struct
import subprocess
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "charts" / "takserver" / "files" / "scripts" / "move-ca-key.sh"
ISSUE = ROOT / "charts" / "takserver" / "files" / "scripts" / "issue-web-cert.sh"
SPLIT = ROOT / "charts" / "takserver" / "files" / "scripts" / "split-key-material.sh"
PUBLISH = ROOT / ".github" / "container-and-chart" / "docker" / "publish-cert-configmap.sh"
PREREQS = ROOT / "charts" / "takserver" / "templates" / "prereqs.yaml"
HELPER_START = "# Retry a refused or reset handshake."


def strip_json(body: str) -> str:
    completed = subprocess.run(
        ["bash", "-c", 'MOVE_CA_KEY_SOURCE_ONLY=1; source "$1"; printf %s "$2" | strip_ca_key_json', "bash", str(SCRIPT), body],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def helper_text(path: Path) -> str:
    text = path.read_text()
    start = text.index(HELPER_START)
    end = text.index("\n}\n", start)
    return text[start : end + 2]


def run_api_curl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'MOVE_CA_KEY_SOURCE_ONLY=1; source "$1"; api_curl "${@:2}"',
            "bash",
            str(SCRIPT),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=25,
    )


def serve_once(drops: int, status: int, body: bytes) -> dict[str, int]:
    """Accept connections. The first `drops` are reset; the next is one HTTP response."""
    info: dict[str, int] = {"hits": 0, "port": 0}
    ready = threading.Event()

    def run() -> None:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        sock.settimeout(15)
        info["port"] = sock.getsockname()[1]
        remaining = drops
        ready.set()
        try:
            while True:
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    return
                info["hits"] += 1
                if remaining > 0:
                    remaining -= 1
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    conn.close()
                    continue
                conn.settimeout(2)
                data = b""
                try:
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                except OSError:
                    conn.close()
                    return
                payload = f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
                try:
                    conn.sendall(payload)
                except OSError:
                    pass
                conn.close()
                return
        finally:
            sock.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(2):
        raise RuntimeError("retry test server did not bind")
    return info


class MoveCaKeyTests(unittest.TestCase):
    def test_middle_field_is_removed(self):
        body = '{"binaryData":{"ca.pem":"YQ==","ca-do-not-share.key":"Yg==","admin.pem":"Yw=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn("ca.pem", got)
        self.assertIn("admin.pem", got)

    def test_first_field_is_removed(self):
        body = '{"binaryData":{"ca-do-not-share.key":"Yg==","ca.pem":"YQ=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn('"ca.pem":"YQ=="', got)

    def test_last_field_is_removed(self):
        body = '{"binaryData":{"ca.pem":"YQ==","ca-do-not-share.key":"Yg=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn('"ca.pem":"YQ=="', got)

    def test_hook_scripts_share_the_retry_helper(self):
        block = helper_text(SCRIPT)
        self.assertIn("--retry 5", block)
        self.assertIn("--retry-delay 1", block)
        self.assertIn("--retry-all-errors", block)
        self.assertIn("--retry-connrefused", block)
        self.assertEqual(helper_text(ISSUE), block)
        self.assertEqual(helper_text(PUBLISH), block)
        self.assertEqual(helper_text(SPLIT), block)

    def test_cert_job_runs_the_split_after_the_ca_move(self):
        text = PREREQS.read_text()
        move = text.index("files/scripts/move-ca-key.sh")
        split = text.index("files/scripts/split-key-material.sh")
        self.assertLess(move, split)
        # move-ca-key.sh exits 0 once the CA key is in its Secret. That
        # script is inlined, so the exit has to stay inside a subshell.
        opening = text[:move].splitlines()[-2].strip()
        self.assertEqual(opening, "(")

    def test_dropped_handshake_is_retried(self):
        info = serve_once(drops=2, status=200, body=b"moved")
        plain = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "5",
                "-o",
                "/dev/null",
                f"http://127.0.0.1:{info['port']}/ca",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(plain.returncode, 0)

        info = serve_once(drops=2, status=200, body=b"moved")
        completed = run_api_curl(
            ["-f", "-o", "-", f"http://127.0.0.1:{info['port']}/ca"]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "moved")
        self.assertGreaterEqual(info["hits"], 3)

    def test_http_409_is_not_retried(self):
        info = serve_once(drops=0, status=409, body=b"exists")
        completed = run_api_curl(
            ["-o", "/dev/null", "-w", "%{http_code}", f"http://127.0.0.1:{info['port']}/secrets"]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "409")
        self.assertEqual(info["hits"], 1)


def source_split(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'SPLIT_KEY_SOURCE_ONLY=1; source "$1"; shift; "$@"',
            "bash",
            str(SPLIT),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def split_fields(body: str, section: str) -> list[tuple[str, str]]:
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'SPLIT_KEY_SOURCE_ONLY=1; source "$1"; printf %s "$2" | data_fields "$3"',
            "bash",
            str(SPLIT),
            body,
            section,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    rows = []
    for line in completed.stdout.splitlines():
        name, value = line.split("\t", 1)
        rows.append((name, value))
    return rows


class SplitKeyTests(unittest.TestCase):
    def test_private_material_matches_the_publish_script(self):
        names = [
            "admin.key",
            "ca-do-not-share.key",
            "takserver.jks",
            "takserver-web.jks",
            "ca-signing.jks",
            "admin.p12",
            "truststore-root.jks",
            "fed-truststore.jks",
            "truststore-root-legacy.p12",
            "ca.pem",
            "admin.pem",
            "admin.csr",
        ]
        for name in names:
            split = source_split("is_private_material", name)
            publish = subprocess.run(
                [
                    "bash",
                    "-c",
                    'PUBLISH_CERT_SOURCE_ONLY=1; source "$1"; is_private_material "$2"',
                    "bash",
                    str(PUBLISH),
                    name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(split.returncode, publish.returncode, name)
            self.assertIn(split.returncode, (0, 1), name)
        self.assertEqual(source_split("is_private_material", "admin.key").returncode, 0)
        self.assertEqual(source_split("is_private_material", "truststore-root.jks").returncode, 1)
        self.assertEqual(source_split("is_private_material", "ca.pem").returncode, 1)

    def test_fields_come_from_the_named_object(self):
        body = (
            '{"metadata":{"name":"cert-migration","managedFields":'
            '[{"manager":"kubectl","fieldsV1":{"f:binaryData":{"f:ca.pem":{}}}}]},'
            '"binaryData":{"ca.pem":"YQ==","takserver.jks":"Yg==","admin.key":"Yw==",'
            '"truststore-root.jks":"ZA=="}}'
        )
        self.assertEqual(
            split_fields(body, "binaryData"),
            [
                ("ca.pem", "YQ=="),
                ("takserver.jks", "Yg=="),
                ("admin.key", "Yw=="),
                ("truststore-root.jks", "ZA=="),
            ],
        )
        self.assertEqual(split_fields(body, "data"), [])

    def test_pretty_printed_object_and_base64(self):
        body = """
        {
          "data": {
            "admin.key": "Y+/=",
            "ca.pem": "YQ=="
          }
        }
        """
        self.assertEqual(
            split_fields(body, "data"),
            [("admin.key", "Y+/="), ("ca.pem", "YQ==")],
        )

    def test_truncated_object_is_rejected(self):
        completed = subprocess.run(
            [
                "bash",
                "-c",
                'SPLIT_KEY_SOURCE_ONLY=1; source "$1"; printf %s "$2" | data_fields binaryData',
                "bash",
                str(SPLIT),
                '{"binaryData":{"ca.pem":"YQ=="',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
