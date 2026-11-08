# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Opt-in ATAK viewer check against Prometheus instant-query semantics.

The default ATAK e2e run leaves uptime_probe off. This is the opted-in case:
a local query API selects the newest sample inside the default five-minute
lookback and stamps that sample with the evaluation time. timestamp(metric)
carries the scrape time. A successful sample that is still inside the lookback
and older than 120 seconds must fail.
"""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import unittest
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("atak_uptime", ROOT / "atak/ci/uptime-probe.py")
uptime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uptime)
TARGET = "https://atak.uds.dev/phone.html"
NOW = 1_800_000_000
# Prometheus --query.lookback-delta default. A sample this old is omitted.
LOOKBACK = 300
SELECTOR = re.compile(
    r'^(timestamp\()?([A-Za-z_][A-Za-z0-9_]*)\{instance="((?:\\.|[^"\\])*)"\}(\))?$'
)


class Sample:
    def __init__(self, name, instance, scraped, value, stale=False):
        self.name = name
        self.instance = instance
        self.scraped = float(scraped)
        self.value = str(value)
        self.stale = stale


def success_samples(scraped, **overrides):
    values = dict(uptime.METRICS)
    values.update(overrides)
    return [Sample(name, TARGET, scraped, value) for name, value in values.items()]


def select_sample(samples, name, instance, evaluated, lookback=LOOKBACK):
    """Newest sample at or before the evaluation time, inside the lookback.

    A stale marker is not returned, and it hides any older sample. Equality
    with the lookback delta is outside the window.
    """
    earlier = [
        sample for sample in samples
        if sample.name == name and sample.instance == instance and sample.scraped <= evaluated
    ]
    if not earlier:
        return None
    chosen = max(earlier, key=lambda sample: sample.scraped)
    if evaluated - chosen.scraped >= lookback or chosen.stale:
        return None
    return chosen


def parse_query(query):
    match = SELECTOR.fullmatch(query)
    if not match:
        return None
    opened, name, instance, closed = match.groups()
    if bool(opened) != bool(closed):
        return None
    return bool(opened), name, json.loads('"' + instance + '"')


def prom_number(number):
    number = float(number)
    if number.is_integer():
        return str(int(number))
    return format(number, ".12f").rstrip("0").rstrip(".")


def evaluate_instant(samples, query, evaluated, lookback=LOOKBACK):
    """Instant-query JSON for one selector, or timestamp() of that selector."""
    parsed = parse_query(query)
    if parsed is None:
        return {"status": "error", "errorType": "bad_data", "error": "unsupported query"}
    want_timestamp, name, instance = parsed
    chosen = select_sample(samples, name, instance, evaluated, lookback)
    if chosen is None:
        result = []
    elif want_timestamp:
        # The sample timestamp stays the evaluation time. The scrape time is
        # the sample value, and __name__ is dropped.
        result = [{"metric": {"instance": instance}, "value": [evaluated, prom_number(chosen.scraped)]}]
    else:
        result = [{
            "metric": {"__name__": name, "instance": instance},
            "value": [evaluated, chosen.value],
        }]
    return {"status": "success", "data": {"resultType": "vector", "result": result}}


class QueryAPI(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/query":
            self._json(404, {"status": "error"})
            return
        params = parse_qs(parsed.query)
        query = params.get("query", [""])[0]
        when = params.get("time", [None])[0]
        self.server.queries.append((query, when))
        evaluated = float(when) if when is not None else self.server.evaluated
        self._json(200, evaluate_instant(self.server.samples, query, evaluated, self.server.lookback))

    def _json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


class Prometheus:
    def __init__(self, samples, evaluated):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QueryAPI)
        self.httpd.samples = samples
        self.httpd.evaluated = float(evaluated)
        self.httpd.lookback = LOOKBACK
        self.httpd.queries = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"
        return self

    def __exit__(self, *_args):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def vector(result):
    return {"status": "success", "data": {"resultType": "vector", "result": result}}


class AtakUptimeTests(unittest.TestCase):
    def test_authenticated_probe_targets_the_viewer_page(self):
        probe = {"spec": {"module": uptime.MODULE, "targets": {"staticConfig": {"static": [TARGET]}}}}
        uptime.validate_probe(probe, TARGET)
        for module in ("http_2xx", "http_200x_sso_cloudtak_other-client", None):
            changed = copy.deepcopy(probe)
            changed["spec"]["module"] = module
            with self.subTest(module=module), self.assertRaises(ValueError):
                uptime.validate_probe(changed, TARGET)
        probe["spec"]["targets"]["staticConfig"]["static"] = ["https://sso.uds.dev/"]
        with self.assertRaises(ValueError):
            uptime.validate_probe(probe, TARGET)

    def test_opt_in_check_accepts_a_fresh_authenticated_viewer(self):
        scraped = NOW - 30
        with Prometheus(success_samples(scraped), NOW) as prometheus:
            evidence = uptime.query_prometheus(prometheus.base, TARGET, now=NOW)
            queries = list(prometheus.httpd.queries)
        self.assertEqual(
            [(row["metric"], row["instance"], row["value"], row["timestamp"]) for row in evidence],
            [(name, TARGET, value, float(scraped)) for name, value in uptime.METRICS.items()],
        )
        self.assertTrue(all(row["timestamp"] != NOW for row in evidence))
        issued = [query for query, _when in queries]
        for name in uptime.METRICS:
            self.assertIn(f'{name}{{instance="{TARGET}"}}', issued)
            self.assertIn(f'timestamp({name}{{instance="{TARGET}"}})', issued)
        self.assertEqual({when for _query, when in queries}, {f"{float(NOW):.3f}"})
        self.assertTrue(all(query.count("(") <= 1 for query in issued))

    def test_success_inside_lookback_older_than_120_seconds_is_rejected(self):
        query = f'probe_success{{instance="{TARGET}"}}'
        for age in (121, 180, 299):
            with self.subTest(age=age):
                self.assertLess(age, LOOKBACK)
                instant = evaluate_instant(success_samples(NOW - age), query, NOW)
                self.assertEqual(instant["data"]["result"][0]["value"], [NOW, "1"])
                stamped = evaluate_instant(success_samples(NOW - age), f"timestamp({query})", NOW)
                self.assertEqual(stamped["data"]["result"][0]["value"][0], NOW)
                self.assertEqual(stamped["data"]["result"][0]["value"][1], str(NOW - age))
                self.assertNotIn("__name__", stamped["data"]["result"][0]["metric"])
                with Prometheus(success_samples(NOW - age), NOW) as prometheus:
                    with self.assertRaises(ValueError) as caught:
                        uptime.query_prometheus(prometheus.base, TARGET, now=NOW)
                self.assertIn("stale or future sample", str(caught.exception))

    def test_sample_aged_exactly_120_seconds_passes(self):
        with Prometheus(success_samples(NOW - uptime.FRESH_SECONDS), NOW) as prometheus:
            evidence = uptime.query_prometheus(prometheus.base, TARGET, now=NOW)
        self.assertEqual(evidence[0]["timestamp"], float(NOW - uptime.FRESH_SECONDS))

    def test_lookback_boundary_and_stale_marker_omit_the_series(self):
        query = f'probe_success{{instance="{TARGET}"}}'
        self.assertEqual(
            evaluate_instant(success_samples(NOW - LOOKBACK), query, NOW)["data"]["result"],
            [],
        )
        hidden = success_samples(NOW - 60)
        hidden.append(Sample("probe_success", TARGET, NOW - 10, "1", stale=True))
        self.assertEqual(evaluate_instant(hidden, query, NOW)["data"]["result"], [])
        self.assertIsNotNone(select_sample(success_samples(NOW - 60), "probe_success", TARGET, NOW))
        for samples in (success_samples(NOW - LOOKBACK), hidden):
            with self.subTest(samples=samples), Prometheus(samples, NOW) as prometheus:
                with self.assertRaises(ValueError) as caught:
                    uptime.query_prometheus(prometheus.base, TARGET, now=NOW)
                self.assertIn("expected one", str(caught.exception))

    def test_wrong_value_wrong_target_and_failed_queries_are_rejected(self):
        cases = (
            success_samples(NOW - 15, probe_success="0"),
            success_samples(NOW - 15, probe_http_status_code="302"),
            success_samples(NOW - 15, probe_http_redirects="1"),
            [Sample(name, "https://sso.uds.dev/", NOW - 15, value) for name, value in uptime.METRICS.items()],
        )
        for samples in cases:
            with self.subTest(samples=samples), Prometheus(samples, NOW) as prometheus:
                with self.assertRaises(ValueError):
                    uptime.query_prometheus(prometheus.base, TARGET, now=NOW)

        value = vector([{"metric": {"__name__": "probe_success", "instance": TARGET}, "value": [NOW, "1"]}])
        fresh = vector([{"metric": {"instance": TARGET}, "value": [NOW, str(NOW)]}])
        with self.assertRaises(ValueError):
            uptime.validate_metric(
                "probe_success", "1", value,
                vector([{"metric": {"instance": TARGET}, "value": [NOW, str(NOW + 1)]}]),
                TARGET,
            )
        with self.assertRaises(ValueError):
            uptime.validate_metric(
                "probe_success", "1", value,
                vector([{"metric": {"instance": TARGET}, "value": [NOW, "not-a-time"]}]),
                TARGET,
            )
        for response in (
            {"status": "error", "data": {}},
            {"status": "success", "data": {"resultType": "matrix", "result": []}},
            vector([]),
            vector([
                {"metric": {"__name__": "probe_success", "instance": TARGET, "job": "a"}, "value": [NOW, "1"]},
                {"metric": {"__name__": "probe_success", "instance": TARGET, "job": "b"}, "value": [NOW, "1"]},
            ]),
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                uptime.validate_metric("probe_success", "1", response, fresh, TARGET)


# Chart pin from uds-core v1.16.0 src/prometheus-stack/common/zarf.yaml, the
# kube-prometheus-stack inside core-monitoring 1.16.0-upstream.
KPS_CHART = "prometheus-community/kube-prometheus-stack"
KPS_VERSION = "92.14.0"
KPS_REPO = "https://prometheus-community.github.io/helm-charts"


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def bundle_overrides():
    bundle = load_yaml("atak/ci/monitoring/uds-bundle.yaml")
    package = bundle["packages"][0]
    if package["name"] != "core-monitoring" or package["ref"] != "1.16.0-upstream":
        raise AssertionError("opt-in bundle must keep core-monitoring 1.16.0-upstream")
    return package["overrides"]


def value_map(overrides, component, chart):
    return {item["path"]: item["value"] for item in overrides[component][chart]["values"]}


def nest_values(paths):
    root = {}
    for path, value in paths.items():
        cursor = root
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return root


def render_prometheus_stack(values):
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required to render kube-prometheus-stack 92.14.0")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        values_path = tmp / "values.yaml"
        values_path.write_text(yaml.safe_dump(values))
        env = os.environ.copy()
        env["HELM_CONFIG_HOME"] = str(tmp / "config")
        env["HELM_CACHE_HOME"] = str(tmp / "cache")
        env["HELM_DATA_HOME"] = str(tmp / "data")
        subprocess.run(
            [helm, "repo", "add", "prometheus-community", KPS_REPO],
            check=True, env=env, capture_output=True, text=True,
        )
        subprocess.run(
            [helm, "repo", "update", "prometheus-community"],
            check=True, env=env, capture_output=True, text=True,
        )
        rendered = subprocess.run(
            [helm, "template", "kps", KPS_CHART, "--version", KPS_VERSION,
             "--namespace", "monitoring", "-f", str(values_path)],
            check=True, env=env, capture_output=True, text=True,
        )
    return [doc for doc in yaml.safe_load_all(rendered.stdout) if isinstance(doc, dict)]


def named(docs, kind):
    return [
        (doc.get("metadata") or {}).get("name")
        for doc in docs
        if doc.get("kind") == kind
    ]


def vm_domain(doc):
    return doc["spec"]["template"]["spec"]["domain"]


def smoke_vm():
    text = (ROOT / "atak/ci/vm-smoke.sh").read_text()
    marker = "cat <<YAML | kubectl apply -n \"${NS}\" -f -\n"
    start = text.index(marker) + len(marker)
    body = text[start:text.index("\nYAML\n", start)]
    return yaml.safe_load(body)


class MonitoringBundleTests(unittest.TestCase):
    def test_opt_in_bundle_keeps_prometheus_and_drops_state_metrics(self):
        overrides = bundle_overrides()
        self.assertEqual(set(overrides), {"grafana", "kube-prometheus-stack"})
        self.assertEqual(value_map(overrides, "grafana", "grafana"), {"replicas": 0})
        stack = value_map(overrides, "kube-prometheus-stack", "kube-prometheus-stack")
        self.assertEqual(stack["kubeStateMetrics.enabled"], False)
        self.assertNotIn("kube-state-metrics.enabled", stack)
        self.assertEqual(stack["alertmanager.enabled"], False)
        self.assertEqual(stack["nodeExporter.enabled"], False)
        self.assertEqual(stack["prometheus-node-exporter.enabled"], False)
        self.assertEqual(stack["prometheus.prometheusSpec.resources.requests.memory"], "256Mi")
        self.assertEqual(stack["prometheus.prometheusSpec.resources.limits.memory"], "1Gi")

        rendered = render_prometheus_stack(nest_values(stack))
        self.assertFalse(any("kube-state-metrics" in (name or "") for name in named(rendered, "Deployment")))
        self.assertFalse(any("node-exporter" in (name or "") for name in named(rendered, "DaemonSet")))
        self.assertNotIn("Alertmanager", {doc.get("kind") for doc in rendered})
        prometheus = [doc for doc in rendered if doc.get("kind") == "Prometheus"]
        self.assertEqual(len(prometheus), 1)
        self.assertEqual(
            prometheus[0]["spec"]["resources"]["requests"]["memory"],
            "256Mi",
        )

        stale = dict(stack)
        stale.pop("kubeStateMetrics.enabled")
        stale["kube-state-metrics.enabled"] = False
        still_there = render_prometheus_stack(nest_values(stale))
        self.assertTrue(any(name == "kps-kube-state-metrics" for name in named(still_there, "Deployment")))
        self.assertEqual(len([doc for doc in still_there if doc.get("kind") == "Prometheus"]), 1)

    def test_device_guest_is_2gi_without_overcommit_or_graphics_changes(self):
        device_docs = [
            doc for doc in yaml.safe_load_all((ROOT / "atak/deploy/device.yaml").read_text())
            if isinstance(doc, dict)
        ]
        vms = [smoke_vm(), next(doc for doc in device_docs if doc.get("kind") == "VirtualMachine")]
        for vm in vms:
            domain = vm_domain(vm)
            self.assertEqual(domain["memory"]["guest"], "2Gi")
            self.assertEqual(domain["cpu"]["cores"], 2)
            self.assertNotIn("resources", domain)
            self.assertNotIn("autoattachGraphicsDevice", domain["devices"])
            self.assertIn("video=720x1280", domain["firmware"]["kernelBoot"]["kernelArgs"])


if __name__ == "__main__":
    unittest.main()
