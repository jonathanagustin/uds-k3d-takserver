#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Require fresh, authenticated Blackbox metrics for the ATAK viewer page.

Run after atak/ci/e2e.sh with Core monitoring installed. Does not read probe
client credentials or alter the operator-owned Blackbox configuration.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import urlopen

MODULE = "http_200x_sso_atak_uds-atak-viewer-probe"
METRICS = {"probe_success": "1", "probe_http_status_code": "200", "probe_http_redirects": "0"}


def validate_probe(probe, target):
    """A generic redirect-following http_2xx probe must never satisfy this test."""
    spec = probe.get("spec", {})
    targets = spec.get("targets", {}).get("staticConfig", {}).get("static", [])
    if spec.get("module") != MODULE or targets != [target]:
        raise ValueError("ATAK Probe must use its SSO module and the exact /phone.html target")


def validate_metrics(response, target, now):
    if response.get("status") != "success" or response.get("data", {}).get("resultType") != "vector":
        raise ValueError("Prometheus did not return a successful instant vector")
    found = set()
    evidence = []
    for row in response["data"].get("result", []):
        labels = row.get("metric", {})
        name = labels.get("__name__")
        if labels.get("instance") != target or name not in METRICS:
            continue
        sample = row.get("value", [])
        if len(sample) != 2:
            raise ValueError(f"missing sample for {name}")
        timestamp, value = sample
        if not 0 <= now - float(timestamp) <= 120:
            raise ValueError(f"stale or future sample for {name}")
        if str(value) != METRICS[name]:
            raise ValueError(f"{name}={value}, expected {METRICS[name]}")
        found.add(name)
        evidence.append({"metric": name, "instance": target, "timestamp": timestamp, "value": value})
    if found != set(METRICS):
        raise ValueError("missing ATAK metrics: " + ", ".join(sorted(set(METRICS) - found)))
    return evidence


def kubectl(*args):
    return subprocess.run(["uds", "zarf", "tools", "kubectl", *args],
                          check=True, capture_output=True, text=True, timeout=30).stdout


def wait_for(check, timeout, description):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return check()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            last_error = error
            time.sleep(5)
    raise RuntimeError(f"{description} did not pass: {last_error}")


def main():
    domain = os.environ.get("DOMAIN", "uds.dev")
    target = f"https://atak.{domain}/phone.html"
    output = Path(os.environ.get("OUT", "out"))
    output.mkdir(parents=True, exist_ok=True)

    def probe_ready():
        probe = json.loads(kubectl("get", "probe", "uds-atak-tenant-uptime", "-n", "atak", "-o", "json"))
        validate_probe(probe, target)
        return {"name": probe["metadata"]["name"], "namespace": "atak", "module": MODULE, "target": target}

    probe = wait_for(probe_ready, 180, "operator-generated authenticated ATAK Probe")
    print(json.dumps(probe), flush=True)
    with tempfile.TemporaryDirectory() as temporary:
        with open(Path(temporary) / "port-forward.log", "w+") as log:
            forward = subprocess.Popen([
                "uds", "zarf", "tools", "kubectl", "port-forward", "-n", "monitoring",
                "svc/kube-prometheus-stack-prometheus", "19091:9090",
            ], stdout=log, stderr=log)
            try:
                def ready():
                    if forward.poll() is not None:
                        raise ValueError("Prometheus port-forward exited")
                    with urlopen("http://127.0.0.1:19091/-/ready", timeout=3) as response:
                        if response.status != 200:
                            raise ValueError("Prometheus is not ready")

                wait_for(ready, 60, "Prometheus port-forward")
                query = '{__name__=~"probe_success|probe_http_status_code|probe_http_redirects",instance=' + json.dumps(target) + '}'
                url = "http://127.0.0.1:19091/api/v1/query?" + urlencode({"query": query})

                def metrics_ready():
                    with urlopen(url, timeout=15) as response:
                        data = json.load(response)
                    return validate_metrics(data, target, time.time())

                evidence = wait_for(metrics_ready, 300, "fresh ATAK viewer uptime metrics")
                result = {"probe": probe, "metrics": evidence}
                (output / "atak-uptime-probe.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(result, indent=2))
                print("ATAK /phone.html probe_success=1, HTTP 200, zero redirects through the operator's SSO module")
            finally:
                forward.terminate()
                try:
                    forward.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forward.kill()
                    forward.wait(timeout=5)


if __name__ == "__main__":
    main()
