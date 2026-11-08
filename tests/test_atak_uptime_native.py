# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Viewer freshness check against a real Prometheus server.

tests/test_atak_uptime.py answers its own stand-in for /api/v1/query. This
file starts Prometheus, lets it scrape samples, and calls query_prometheus.
A successful sample older than 120 seconds and still inside the lookback is
rejected. Nothing here deploys Blackbox, Core monitoring, or the ATAK device.

Set PROMETHEUS_BIN to the prometheus binary. Without it, the module skips so
a local unittest discover can run. The workflow sets the variable and fails
if the binary is missing.
"""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("atak_uptime", ROOT / "atak/ci/uptime-probe.py")
uptime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uptime)

TARGET = "https://atak.uds.dev/phone.html"
PROM_BIN = os.environ.get("PROMETHEUS_BIN", "")
EVIDENCE = Path(os.environ.get("NATIVE_EVIDENCE", "out/atak-uptime-native.json"))
LOOKBACK = 300


class Exposition(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/metrics":
            self._send(404, b"")
            return
        body = self.server.body
        self._send(200, body, "text/plain; version=0.0.4")

    def _send(self, status, body, content_type="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def exposition(values, scraped):
    millis = int(scraped) * 1000
    lines = []
    for name, value in values.items():
        lines.append(f"# TYPE {name} gauge")
        lines.append(f'{name}{{instance="{TARGET}"}} {value} {millis}')
    return ("\n".join(lines) + "\n").encode()


def query_api(base, query, when):
    url = base + "/api/v1/query?" + urlencode({"query": query, "time": f"{float(when):.3f}"})
    with urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise AssertionError(f"Prometheus HTTP {response.status}")
        return json.load(response)


class Prometheus:
    def __init__(self, body):
        self.metrics = ThreadingHTTPServer(("127.0.0.1", 0), Exposition)
        self.metrics.body = body
        self.metrics_thread = threading.Thread(target=self.metrics.serve_forever, daemon=True)
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.port = free_port()
        metrics_port = self.metrics.server_address[1]
        config = root / "prometheus.yml"
        config.write_text(
            "global:\n"
            "  scrape_interval: 1s\n"
            "  scrape_timeout: 1s\n"
            "scrape_configs:\n"
            "  - job_name: atak-viewer\n"
            "    honor_labels: true\n"
            "    honor_timestamps: true\n"
            "    metrics_path: /metrics\n"
            "    static_configs:\n"
            f"      - targets: ['127.0.0.1:{metrics_port}']\n"
        )
        log_path = root / "prometheus.log"
        self.log = log_path.open("w+")
        self.process = subprocess.Popen(
            [
                PROM_BIN,
                f"--config.file={config}",
                f"--storage.tsdb.path={root / 'data'}",
                f"--web.listen-address=127.0.0.1:{self.port}",
                "--log.level=warn",
            ],
            cwd=str(Path(PROM_BIN).resolve().parent),
            stdout=self.log,
            stderr=self.log,
        )
        self.base = f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.metrics_thread.start()
        return self

    def __exit__(self, *_args):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()
        self.metrics.shutdown()
        self.metrics.server_close()
        self.metrics_thread.join(timeout=5)
        self.directory.cleanup()

    def ready(self):
        with urlopen(self.base + "/-/ready", timeout=2) as response:
            if response.status != 200:
                raise OSError(f"ready HTTP {response.status}")

    def wait_ready(self):
        deadline = time.monotonic() + 20
        last = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("Prometheus exited\n" + self.log_text())
            try:
                self.ready()
                return
            except OSError as error:
                last = error
                time.sleep(0.2)
        raise AssertionError(f"Prometheus did not become ready: {last}\n{self.log_text()}")

    def log_text(self):
        self.log.flush()
        return Path(self.log.name).read_text(errors="replace")[-4000:]


def series(base, name, when):
    body = query_api(base, f'{name}{{instance="{TARGET}"}}', when)
    result = body.get("data", {}).get("result", [])
    if body.get("status") != "success" or not result:
        raise OSError("series not scraped yet")
    return result[0]


def wait_series(prom, when):
    deadline = time.monotonic() + 20
    last = None
    while time.monotonic() < deadline:
        try:
            return series(prom.base, "probe_success", when)
        except OSError as error:
            last = error
            time.sleep(0.3)
    raise AssertionError(f"{last}\n{prom.log_text()}")


def record(case):
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"prometheus": "native", "cases": []}
    if EVIDENCE.exists():
        payload = json.loads(EVIDENCE.read_text())
    payload["cases"].append(case)
    EVIDENCE.write_text(json.dumps(payload, indent=2) + "\n")


def require_binary():
    if os.environ.get("REQUIRE_NATIVE") == "1" and (not PROM_BIN or not os.access(PROM_BIN, os.X_OK)):
        raise RuntimeError("PROMETHEUS_BIN must be an executable Prometheus binary")


require_binary()


@unittest.skipUnless(PROM_BIN and os.access(PROM_BIN, os.X_OK), "set PROMETHEUS_BIN to a Prometheus binary")
class NativePrometheusTests(unittest.TestCase):
    def run_case(self, name, age, values):
        scraped = int(time.time()) - age
        with Prometheus(exposition(values, scraped)) as prom:
            prom.wait_ready()
            when = time.time()
            sample = wait_series(prom, when)
            stamped = query_api(prom.base, f'timestamp(probe_success{{instance="{TARGET}"}})', when)
            stamp = stamped["data"]["result"][0]
            evaluated = float(sample["value"][0])
            scrape_time = float(stamp["value"][1])
            # The instant sample is stamped with the evaluation time. The
            # scrape time is only in timestamp()'s value.
            self.assertLess(abs(evaluated - when), 1.5, sample)
            self.assertGreater(abs(evaluated - scraped), age - 2, sample)
            self.assertLess(abs(scrape_time - scraped), 0.001, stamp)
            self.assertNotIn("__name__", stamp["metric"])
            outcome = {
                "accepted": False,
                "error": "",
                "instant_probe_success": sample["value"],
                "scrape_time": scrape_time,
            }
            try:
                evidence = uptime.query_prometheus(prom.base, TARGET, now=when)
            except ValueError as error:
                outcome["error"] = str(error)
            else:
                outcome["accepted"] = True
                outcome["evidence"] = evidence
            record({
                "name": name,
                "age_seconds": age,
                "values": values,
                "evaluation_time": evaluated,
                "scrape_time": scrape_time,
                "instant_probe_success": sample["value"],
                "timestamp_probe_success": stamp["value"],
                **outcome,
            })
            return outcome

    def test_fresh_success_is_accepted(self):
        outcome = self.run_case("fresh-success", 30, dict(uptime.METRICS))
        self.assertTrue(outcome["accepted"], outcome)
        self.assertEqual(
            [row["value"] for row in outcome["evidence"]],
            list(uptime.METRICS.values()),
        )
        self.assertTrue(all(abs(row["timestamp"] - outcome["scrape_time"]) < 0.001 for row in outcome["evidence"]))

    def test_success_inside_lookback_older_than_120_seconds_is_rejected(self):
        self.assertLess(180, LOOKBACK)
        outcome = self.run_case("stale-within-lookback", 180, dict(uptime.METRICS))
        self.assertFalse(outcome["accepted"], outcome)
        self.assertIn("stale or future sample", outcome["error"])
        self.assertEqual(outcome["instant_probe_success"][1], "1")

    def test_broken_status_is_rejected(self):
        values = dict(uptime.METRICS)
        values["probe_http_status_code"] = "302"
        values["probe_http_redirects"] = "1"
        outcome = self.run_case("broken-redirect", 20, values)
        self.assertFalse(outcome["accepted"], outcome)
        self.assertIn("probe_http_status_code=302", outcome["error"])


if __name__ == "__main__":
    unittest.main()
