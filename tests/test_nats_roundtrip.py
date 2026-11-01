# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Run the chart 1.0.1 config on NATS 2.15.1 and exercise core pub/sub."""

import importlib.util
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "nats_roundtrip", Path(__file__).with_name("nats-roundtrip.py")
)
nats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nats)

SERVER_IMAGE = "nats:2.15.1-alpine"
RELOADER_IMAGE = "natsio/nats-server-config-reloader:0.25.0"


def _docker(*args, check=True):
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True
    )


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class NatsRoundtripTests(unittest.TestCase):
    def test_chart_config_survives_a_restart(self):
        if shutil.which("docker") is None or _docker("info", check=False).returncode != 0:
            self.skipTest("docker is not available")
        name = "nats-roundtrip-test"
        reloader = "nats-reloader-test"
        port = _free_port()
        _docker("rm", "-f", name, reloader, check=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "nats.conf"
            config.write_text(nats.CHART_CONFIG)
            pid_dir = root / "pid"
            pid_dir.mkdir()
            pid_dir.chmod(0o777)
            _docker(
                "run",
                "-d",
                "--name",
                name,
                "-p",
                "127.0.0.1:%d:4222" % port,
                "-e",
                "SERVER_NAME=nats-0",
                "-v",
                "%s:/etc/nats-config/nats.conf:ro" % config,
                "-v",
                "%s:/var/run/nats" % pid_dir,
                SERVER_IMAGE,
                "--config",
                "/etc/nats-config/nats.conf",
            )
            try:
                self._wait_ready(name)
                info = nats.roundtrip("127.0.0.1", port)
                self.assertIn("server_id", info)
                varz = _docker(
                    "exec",
                    name,
                    "wget",
                    "-qO-",
                    "http://127.0.0.1:8222/varz",
                ).stdout
                self.assertIn('"version": "2.15.1"', varz)
                _docker("restart", name)
                self._wait_ready(name)
                nats.roundtrip("127.0.0.1", port)
                _docker(
                    "run",
                    "-d",
                    "--name",
                    reloader,
                    "--network",
                    "container:%s" % name,
                    "-v",
                    "%s:/etc/nats-config/nats.conf:ro" % config,
                    "-v",
                    "%s:/var/run/nats" % pid_dir,
                    RELOADER_IMAGE,
                    "-pid",
                    "/var/run/nats/nats.pid",
                    "-config",
                    "/etc/nats-config/nats.conf",
                )
                deadline = time.time() + 15
                logs = ""
                while time.time() < deadline:
                    result = _docker("logs", reloader, check=False)
                    logs = result.stdout + result.stderr
                    if "ready to kick" in logs:
                        break
                    time.sleep(0.5)
                self.assertIn("ready to kick", logs)
                status = _docker("inspect", "-f", "{{.State.Status}}", reloader)
                self.assertEqual(status.stdout.strip(), "running")
            finally:
                _docker("rm", "-f", name, reloader, check=False)

    def _wait_ready(self, name):
        deadline = time.time() + 20
        while time.time() < deadline:
            state = _docker("inspect", "-f", "{{.State.Status}}", name).stdout.strip()
            logs = _docker("logs", name, check=False)
            text = logs.stderr + logs.stdout
            if state != "running":
                self.fail("nats exited: %s" % text)
            if "Server is ready" in text:
                return
            time.sleep(0.3)
        self.fail("nats did not become ready")


if __name__ == "__main__":
    unittest.main()
