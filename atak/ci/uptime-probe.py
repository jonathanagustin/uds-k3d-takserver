#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Require fresh, authenticated Blackbox metrics for the ATAK viewer page.

Run after atak/ci/e2e.sh with Core monitoring installed. Does not read probe
client credentials or alter the operator-owned Blackbox configuration.

An instant query reports each sample at the evaluation time and can still
return a value scraped up to the lookback period ago. Freshness is the scrape
time from timestamp() on that selector, and it has to be within 120 seconds.
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
FRESH_SECONDS = 120


def validate_probe(probe, target):
    """A generic redirect-following http_2xx probe must never satisfy this test."""
    spec = probe.get("spec", {})
    targets = spec.get("targets", {}).get("staticConfig", {}).get("static", [])
    if spec.get("module") != MODULE or targets != [target]:
        raise ValueError("ATAK Probe must use its SSO module and the exact /phone.html target")


def selector(name, target):
    return f"{name}{{instance={json.dumps(target)}}}"


def value_query(name, target):
    return selector(name, target)


def scrape_time_query(name, target):
    """timestamp() has to wrap the selector itself so the scrape time is kept."""
    return f"timestamp({selector(name, target)})"


def _vector(response):
    if response.get("status") != "success" or response.get("data", {}).get("resultType") != "vector":
        raise ValueError("Prometheus did not return a successful instant vector")
    result = response["data"].get("result", [])
    if not isinstance(result, list):
        raise ValueError("Prometheus did not return a successful instant vector")
    return result


def _one_sample(response, target, name):
    found = []
    for row in _vector(response):
        labels = row.get("metric", {})
        if labels.get("instance") != target:
            continue
        if name is not None and labels.get("__name__") != name:
            continue
        sample = row.get("value")
        if not isinstance(sample, list) or len(sample) != 2:
            raise ValueError(f"missing sample for {name or 'scrape time'}")
        found.append(sample)
    label = name or "scrape time"
    if len(found) != 1:
        raise ValueError(f"expected one {label} sample for {target}")
    return found[0]


def validate_metric(name, expected, value_response, time_response, target):
    """Accept expected only when timestamp(metric) is 0 to 120 seconds old.

    The value vector's timestamp is the evaluation time. The scrape time is
    the value of the timestamp() vector.
    """
    _evaluation, value = _one_sample(value_response, target, name)
    evaluated, scraped = _one_sample(time_response, target, None)
    try:
        age = float(evaluated) - float(scraped)
    except (TypeError, ValueError) as error:
        raise ValueError(f"scrape time for {name} is not a number") from error
    if not 0 <= age <= FRESH_SECONDS:
        raise ValueError(f"stale or future sample for {name}")
    if str(value) != expected:
        raise ValueError(f"{name}={value}, expected {expected}")
    return {"metric": name, "instance": target, "timestamp": float(scraped), "value": str(value)}


def collect_metrics(fetch, target):
    evidence = []
    for name, expected in METRICS.items():
        evidence.append(validate_metric(
            name,
            expected,
            fetch(value_query(name, target)),
            fetch(scrape_time_query(name, target)),
            target,
        ))
    return evidence


def query_prometheus(base_url, target, opener=urlopen, now=None):
    """Evaluate every selector at one timestamp so the samples are one scrape."""
    if now is None:
        now = time.time()
    evaluated = f"{float(now):.3f}"

    def fetch(query):
        url = base_url.rstrip("/") + "/api/v1/query?" + urlencode({"query": query, "time": evaluated})
        with opener(url, timeout=15) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError(f"Prometheus query failed with HTTP {response.status}")
            return json.load(response)

    return collect_metrics(fetch, target)


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

                def metrics_ready():
                    return query_prometheus("http://127.0.0.1:19091", target)

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
