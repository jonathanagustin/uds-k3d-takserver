# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pareto and log-parser fixtures. These dicts are not benchmark measurements."""

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path


def load(name, relative):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load("bench_report", "bench/report.py")
loadlog = load("bench_loadlog", "bench/loadlog.py")
runner = load("bench_run", "bench/run.py")


def record(config, arch, rss, received, duration, mean, ready):
    return {
        "schema": 1,
        "arch": arch,
        "config": config,
        "kubelet": {"steady_rss_bytes": rss},
        "load": {
            "messages_received": received,
            "duration_s": duration,
            "ping_pong_ms_mean": mean,
        },
        "time_to_ready": {"cold_s": ready, "warm_s": None},
        "errors": [],
    }


class BenchReportTests(unittest.TestCase):
    def test_a_worse_config_is_dominated_on_footprint_and_throughput(self):
        points = [
            {"config": "low", "arch": "amd64", "footprint_bytes": 10, "throughput": 5, "latency_ms": 20, "ready_s": 30, "errors": []},
            {"config": "high", "arch": "amd64", "footprint_bytes": 20, "throughput": 4, "latency_ms": 40, "ready_s": 50, "errors": []},
        ]
        kept, dominated = report.front(points, "footprint_bytes", "throughput", False, True)
        self.assertEqual([item["config"] for item in kept], ["low"])
        self.assertEqual([item["config"] for item in dominated], ["high"])

    def test_a_missing_axis_is_not_plotted(self):
        points = [
            {"config": "gap", "arch": "amd64", "footprint_bytes": 10, "throughput": None, "latency_ms": None, "ready_s": None, "errors": ["load"]},
        ]
        kept, dominated = report.front(points, "footprint_bytes", "throughput", False, True)
        self.assertEqual(kept, [])
        self.assertEqual(dominated, [])

    def test_equal_points_do_not_dominate_each_other(self):
        points = [
            {"config": "one", "arch": "arm64", "footprint_bytes": 10, "throughput": 5, "latency_ms": 1, "ready_s": 1, "errors": []},
            {"config": "two", "arch": "arm64", "footprint_bytes": 10, "throughput": 5, "latency_ms": 1, "ready_s": 1, "errors": []},
        ]
        kept, dominated = report.front(points, "footprint_bytes", "throughput", False, True)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dominated, [])

    def test_markdown_names_the_dominated_config(self):
        records = [
            record("low", "amd64", 10, 50, 10, 5, 20),
            record("high", "amd64", 30, 10, 10, 15, 40),
        ]
        text = report.markdown(records)
        self.assertIn("Dominated: high", text)
        self.assertIn("Front: low", text)


class LoadLogTests(unittest.TestCase):
    def test_last_line_per_uid_is_the_total(self):
        text = "\n".join([
            "Info that would be sent to CloudWatch if it was enabled, uid: PyTAK-0000, stats: {'messages_sent': 1, 'messages_received': 1, 'connect_count': 1, 'disconnect_count': 0, 'ping_count': 1, 'pong_count': 1, 'time_between_ping_pong': 10}",
            "Info that would be sent to CloudWatch if it was enabled, uid: PyTAK-0000, stats: {'messages_sent': 3, 'messages_received': 2, 'connect_count': 1, 'disconnect_count': 0, 'ping_count': 2, 'pong_count': 2, 'time_between_ping_pong': 30}",
            "Info that would be sent to CloudWatch if it was enabled, uid: PyTAK-0001, stats: {'messages_sent': 4, 'messages_received': 4, 'connect_count': 1, 'disconnect_count': 1, 'ping_count': 1, 'pong_count': 0, 'time_between_ping_pong': 0}",
        ])
        parsed = loadlog.parse(text)
        self.assertEqual(parsed["messages_sent"], 7)
        self.assertEqual(parsed["messages_received"], 6)
        self.assertEqual(parsed["pong_count"], 2)
        self.assertEqual(parsed["ping_pong_ms_mean"], 15)
        self.assertIsNone(parsed["p95_ms"])

    def test_a_log_without_stats_is_an_error(self):
        with self.assertRaises(ValueError):
            loadlog.parse("tester started\n")


class ScriptPathTests(unittest.TestCase):
    def test_launching_the_file_can_import_the_parser(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "bench" / "run.py"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        # `python bench/run.py` puts the script directory first and drops cwd.
        probe = (
            "import pathlib, runpy, sys\n"
            "script = pathlib.Path(sys.argv[1]).resolve()\n"
            "sys.path = [str(script.parent), *sys.path[1:]]\n"
            "runpy.run_path(str(script), run_name='bench_probe')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(script)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class ImageRefTests(unittest.TestCase):
    def test_only_image_references_are_kept(self):
        text = "\n".join([
            "    images:",
            '      - "ghcr.io/example/takserver-api:1"',
            "      - name: not-an-image",
            "      - https://example.com/docs",
        ])
        self.assertEqual(runner.image_refs(text), ["ghcr.io/example/takserver-api:1"])

    def test_the_package_lists_tak_images(self):
        text = (Path(__file__).resolve().parents[1] / "zarf.yaml").read_text(encoding="utf-8")
        refs = runner.image_refs(text)
        self.assertTrue(any(ref.startswith("ghcr.io/") and "takserver-api" in ref for ref in refs))


if __name__ == "__main__":
    unittest.main()
