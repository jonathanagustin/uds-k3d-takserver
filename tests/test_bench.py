# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pareto and log-parser fixtures. These dicts are not benchmark measurements."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
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
tester_exit = load("bench_tester_exit", "bench/tester_exit.py")


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
    def test_intervals_are_added(self):
        text = "\n".join([
            "Info that would be sent to CloudWatch if it was enabled, uid: cot_client_0, stats: {'messages_sent': 1, 'messages_received': 1, 'connect_event_count': 1, 'disconnect_event_count': 0, 'ping_count': 1, 'pong_count': 1, 'time_between_ping_pong': 10}",
            "Info that would be sent to CloudWatch if it was enabled, uid: cot_client_0, stats: {'messages_sent': 3, 'messages_received': 2, 'connect_event_count': 1, 'disconnect_event_count': 0, 'ping_count': 2, 'pong_count': 2, 'time_between_ping_pong': 30}",
            "Info that would be sent to CloudWatch if it was enabled, uid: cot_client_1, stats: {'messages_sent': 4, 'messages_received': 4, 'connect_event_count': 1, 'disconnect_event_count': 1, 'ping_count': 1, 'pong_count': 0, 'time_between_ping_pong': 0}",
        ])
        parsed = loadlog.parse(text)
        self.assertEqual(parsed["messages_sent"], 8)
        self.assertEqual(parsed["messages_received"], 7)
        self.assertEqual(parsed["connects"], 3)
        self.assertEqual(parsed["disconnects"], 1)
        self.assertEqual(parsed["pong_count"], 3)
        self.assertEqual(parsed["ping_pong_ms_sum"], 40)
        self.assertEqual(parsed["ping_pong_ms_mean"], 40 / 3)
        self.assertIsNone(parsed["p95_ms"])

    def test_a_log_without_stats_is_an_error(self):
        with self.assertRaises(ValueError):
            loadlog.parse("tester started\n")


class ManifestCommandTests(unittest.TestCase):
    def test_crane_is_used_when_it_is_installed(self):
        command = runner.manifest_command(
            "example/app:1", "amd64", lambda name: "/bin/crane" if name == "crane" else None,
        )
        self.assertEqual(command, ["/bin/crane", "--platform", "linux/amd64", "manifest", "example/app:1"])

    def test_uds_registry_is_used_when_crane_is_absent(self):
        command = runner.manifest_command(
            "example/app:1", "arm64", lambda name: "/bin/uds" if name == "uds" else None,
        )
        self.assertEqual(
            command,
            ["/bin/uds", "zarf", "tools", "registry", "--platform", "linux/arm64", "manifest", "example/app:1"],
        )

    def test_a_missing_tool_is_an_error(self):
        with self.assertRaises(RuntimeError):
            runner.manifest_command("example/app:1", "amd64", lambda name: None)


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


def tester_fixture():
    exit_mod = tester_exit
    return "".join([
        exit_mod.ANCHOR,
        exit_mod.STREAM_LOOP * 3,
        exit_mod.TLS_LOOP,
        exit_mod.START_JOIN * 3,
        exit_mod.TLS_START_JOIN,
        exit_mod.OFFSET_SLEEP * 4,
        "def test_udp():\n",
        exit_mod.UDP_LOOP,
        "                pass\n",
        exit_mod.UDP_TAIL,
        "def test_tcp():\n",
        exit_mod.TCP_LOOP,
        "                pass\n",
    ])


class TesterExitTests(unittest.TestCase):
    def test_the_upstream_loops_gain_a_deadline_and_a_stop(self):
        bound = tester_exit.bind_tester(tester_fixture())
        self.assertIn("_tak_tester_stop_procs", bound)
        self.assertNotIn("while True:", bound)
        self.assertNotIn("p.join()", bound)
        self.assertIn("sock.close()", bound)
        again = tester_exit.bind_tester(bound)
        self.assertEqual(again, bound)

    def test_a_short_deadline_closes_the_client_socket(self):
        script = "import time\n" + tester_exit.HELPER + textwrap.dedent(
            """
            import socket
            class Client:
                def __init__(self):
                    self.sock = socket.socket()
                    self.sock.bind(("127.0.0.1", 0))
                    self.alive = True
                    self.terminated = False
                def is_alive(self):
                    return self.alive
                def terminate(self):
                    self.terminated = True
                    self.alive = False
                def join(self, timeout=None):
                    return None
            procs = [Client()]
            while not _tak_tester_should_stop():
                time.sleep(0.05)
            _tak_tester_stop_procs(procs)
            print("terminated", int(procs[0].terminated))
            fd = procs[0].sock.fileno()
            print("socket-closed" if fd < 0 else "socket-open")
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bounded.py"
            path.write_text(script, encoding="utf-8")
            env = os.environ.copy()
            env["TAK_TESTER_DURATION"] = "1"
            started = time.monotonic()
            completed = subprocess.run(
                [sys.executable, "-u", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                env=env,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("terminated 1", completed.stdout)
        self.assertIn("socket-closed", completed.stdout)

    def test_reap_kills_a_process_that_ignores_sigterm(self):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
            ],
            start_new_session=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        started = time.monotonic()
        tester_exit.reap(proc, 0.3)
        self.assertIsNotNone(proc.poll())
        self.assertLess(time.monotonic() - started, 8)
        self.assertNotEqual(proc.returncode, 0)
        # The group is gone. A second signal finds nobody to kill.
        self.assertFalse(tester_exit.kill_group(proc.pid, signal.SIGKILL))


class PostgresTests(unittest.TestCase):
    def tearDown(self):
        runner._postgres_custom = False

    def test_a_bad_setting_is_refused(self):
        with self.assertRaises(RuntimeError):
            runner.postgres_statements({"shared_buffers": "128MB; DROP TABLE cot"})
        with self.assertRaises(RuntimeError):
            runner.postgres_statements({"shared buffers": "128MB"})

    def test_reset_then_set(self):
        lines = runner.postgres_statements({
            "shared_buffers": "128MB",
            "checkpoint_timeout": "15min",
        })
        self.assertEqual(lines[0], "ALTER SYSTEM RESET ALL")
        self.assertIn("ALTER SYSTEM SET checkpoint_timeout = '15min'", lines)
        self.assertIn("ALTER SYSTEM SET shared_buffers = '128MB'", lines)

    def test_hit_ratio_is_null_when_no_blocks_were_read(self):
        self.assertIsNone(runner.hit_ratio(0, 0))
        self.assertEqual(runner.hit_ratio(3, 1), 0.75)

    def test_assemble_keeps_rss_and_settings(self):
        row = {
            "blks_hit": 3,
            "blks_read": 1,
            "temp_files": 0,
            "temp_bytes": 0,
            "checkpoints_timed": 1,
            "checkpoints_req": 2,
            "checkpoint_write_ms": 4.5,
            "checkpoint_sync_ms": 1,
            "buffers_backend": 9,
            "shared_buffers": "128MB",
            "work_mem": "4MB",
            "effective_cache_size": "384MB",
            "max_wal_size": "256MB",
            "checkpoint_timeout": "5min",
        }
        body = runner.assemble_postgres(row, [100, 250])
        self.assertEqual(body["datname"], "cot")
        self.assertEqual(body["hit_ratio"], 0.75)
        self.assertEqual(body["peak_rss_bytes"], 250)
        self.assertEqual(body["steady_rss_bytes"], 250)
        self.assertEqual(body["settings"]["shared_buffers"], "128MB")
        self.assertIsNone(runner.assemble_postgres({**row, "blks_hit": 0, "blks_read": 0}, [])["hit_ratio"])
        self.assertIsNone(runner.assemble_postgres({**row, "blks_hit": 0, "blks_read": 0}, [])["steady_rss_bytes"])

    def test_apply_resets_a_previous_override(self):
        calls = []

        def fake(*args):
            calls.append(args)

            class Result:
                stdout = ""

            result = Result()
            if args[0] == "get":
                result.stdout = json.dumps({
                    "items": [{"metadata": {"name": "takserver-postgresql-0"}}],
                })
            return result

        self.assertTrue(runner.apply_postgres({"postgres": {"shared_buffers": "64MB"}}, fake))
        text = " ".join(str(part) for part in calls[-1])
        self.assertIn("ALTER SYSTEM RESET ALL", text)
        self.assertIn("ALTER SYSTEM SET shared_buffers = '64MB'", text)
        self.assertIn("takserver-postgresql-0", calls[-1])
        calls.clear()
        self.assertTrue(runner.apply_postgres({"name": "baseline"}, fake))
        text = " ".join(str(part) for part in calls[-1])
        self.assertIn("ALTER SYSTEM RESET ALL", text)
        self.assertNotIn("ALTER SYSTEM SET", text)
        self.assertFalse(runner._postgres_custom)

    def test_an_untouched_database_is_left_alone(self):
        def fake(*_args):
            raise AssertionError("kubectl should not run")

        self.assertFalse(runner.apply_postgres({"name": "baseline"}, fake))

    def test_rollout_restarts_postgres_only_after_a_change(self):
        plain = runner.rollout_items(
            {
                "env": [{"workload": "deployment/takserver-api", "namespace": "takserver"}],
                "resources": [],
            },
            False,
        )
        self.assertEqual([item["workload"] for item in plain], ["deployment/takserver-api"])
        changed = runner.rollout_items({"env": [], "resources": []}, True)
        self.assertEqual(changed[0]["workload"], "statefulset/takserver-postgresql")
        self.assertEqual(changed[0]["namespace"], "takserver")

    def test_the_sweep_configs_stay_inside_the_limit(self):
        root = Path(__file__).resolve().parents[1]
        buffers = runner.load_config(root / "bench" / "configs" / "postgis-buffers.yaml")
        wal = runner.load_config(root / "bench" / "configs" / "postgis-wal.yaml")
        self.assertEqual(buffers["postgres"]["shared_buffers"], "128MB")
        self.assertEqual(wal["postgres"]["shared_buffers"], "64MB")
        self.assertEqual(wal["postgres"]["checkpoint_timeout"], "15min")
        self.assertTrue(buffers["restart"])
        self.assertTrue(wal["restart"])
        for config in (buffers, wal):
            for key in runner.POSTGRES_SETTINGS:
                self.assertIn(key, config["postgres"])
            runner.postgres_statements(config["postgres"])
            self.assertLessEqual(int(config["postgres"]["shared_buffers"][:-2]), 128)

    def test_a_record_starts_with_postgres_unset(self):
        body = runner.blank("amd64", "baseline", 10, 60)
        self.assertIsNone(body["postgres"])
        self.assertEqual(body["schema"], 1)

    def test_the_summary_lists_postgres_next_to_throughput(self):
        sample = record("postgis-buffers", "amd64", 10, 50, 10, 5, 20)
        sample["postgres"] = {
            "hit_ratio": 0.9,
            "temp_bytes": 0,
            "checkpoints_req": 1,
            "steady_rss_bytes": 60000000,
            "settings": {"shared_buffers": "128MB"},
        }
        text = report.markdown([sample])
        self.assertIn("hit_ratio 0.9", text)
        self.assertIn("throughput 5.0", text)
        self.assertIn("shared_buffers 128MB", text)
        self.assertIn("No Postgres stats.", report.markdown([record("baseline", "amd64", 10, 50, 10, 5, 20)]))


if __name__ == "__main__":
    unittest.main()
