# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pareto and log-parser fixtures. These dicts are not benchmark measurements."""

import ast
import contextlib
import io
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch


def load(name, relative):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load("bench_report", "bench/report.py")
loadlog = load("bench_loadlog", "bench/loadlog.py")
phases = load("bench_phases", "bench/phases.py")
runner = load("bench_run", "bench/run.py")
startup = load("bench_startup", "bench/startup.py")
tester_exit = load("bench_tester_exit", "bench/tester_exit.py")


class PrivateLoadFailureTests(unittest.TestCase):
    password = "private-password-sentinel-7462"
    key_text = "private-key-sentinel-9174"

    def fixture(self, stack, root, failure):
        tester = root / "tester.py"
        tester.write_text("# fixture source")
        directories = []
        real_mkdtemp = tempfile.mkdtemp
        def make_dir(**kwargs):
            path = real_mkdtemp(dir=root, **kwargs)
            directories.append(Path(path))
            return path
        stack.enter_context(patch.object(runner.tempfile, "mkdtemp", side_effect=make_dir))
        stack.enter_context(patch.object(runner.time, "sleep"))
        stack.enter_context(patch.object(runner, "kubectl_cmd", return_value=["fixture-kubectl"]))
        stack.enter_context(patch.object(runner, "bind_tester", return_value="# bounded fixture"))
        export_error = subprocess.CalledProcessError(7, ["openssl", "-passin", "pass:" + self.password],
                                                     output=self.key_text, stderr=self.password)
        timeout = subprocess.TimeoutExpired(["python", "--password", self.password], 80,
                                             output=self.key_text, stderr=self.password)
        runs = stack.enter_context(patch.object(runner.subprocess, "run"))
        if failure == "export":
            runs.side_effect = [None, export_error]
        forward = MagicMock()
        forward.poll.return_value = None
        forward.wait.side_effect = [subprocess.TimeoutExpired(["fixture-forward", self.password], 5), 0]
        launch = stack.enter_context(patch.object(runner.subprocess, "Popen"))
        launch.side_effect = [forward, OSError(2, self.password, self.key_text)] if failure == "launch" else [forward, MagicMock()]
        waiter = stack.enter_context(patch.object(runner, "reap"))
        if failure == "timeout":
            waiter.side_effect = timeout
        else:
            waiter.return_value = self.key_text + self.password
        return tester, directories, forward, launch

    def assert_private(self, text):
        self.assertNotIn(self.password, text)
        self.assertNotIn(self.key_text, text)

    def test_subprocess_errors_and_normal_tracebacks_are_private_and_cleanup_runs(self):
        for failure, message in (("export", "certificate export: process failed (exit 7)"),
                                 ("timeout", "load tester wait: process timed out"),
                                 ("launch", "load tester launch: operating system failure (errno 2)"),
                                 ("parse", "load metrics invalid or missing")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                tester, directories, forward, launch = self.fixture(stack, Path(directory), failure)
                try:
                    runner.run_load(50, 60, self.password, tester)
                except (RuntimeError, ValueError) as error:
                    self.assertEqual(str(error), message)
                    self.assert_private("".join(traceback.format_exception(error)))
                    self.assertTrue(error.__suppress_context__)
                else:
                    self.fail("fixture failure was not raised")
                self.assertTrue(all(not path.exists() for path in directories))
                if failure != "export":
                    forward.terminate.assert_called_once()
                    forward.kill.assert_called_once()
                    self.assertEqual(forward.wait.call_count, 2)
                    self.assertIn(self.password, launch.call_args.args[0])

    def test_successful_metrics_and_cleanup_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            tester, directories, forward, _launch = self.fixture(stack, Path(directory), "success")
            stats = {"messages_sent": 5, "messages_received": 6, "connect_event_count": 2,
                     "disconnect_event_count": 0, "pong_count": 2, "time_between_ping_pong": 8}
            runner.reap.return_value = f"Info that would be sent to CloudWatch if it was enabled, uid: fixture, stats: {stats}"
            parsed = runner.run_load(50, 60, self.password, tester)
            self.assertEqual(parsed["connects"], 2)
            self.assertEqual(parsed["messages_received"], 6)
            self.assertEqual(parsed["ping_pong_ms_mean"], 4)
            self.assertTrue(all(not path.exists() for path in directories))
            forward.terminate.assert_called_once()
            forward.kill.assert_called_once()

    def test_public_record_does_not_serialize_credential_bearing_exceptions(self):
        for failure in ("export", "timeout"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                root = Path(directory)
                tester, directories, _forward, _launch = self.fixture(stack, root, failure)
                for name, value in (("git_sha", "a" * 40), ("apply_postgres", False), ("apply_config", None), ("footprint", ({}, [])),
                                    ("start_phases", ({}, [])), ("startup_shape", ({}, [])), ("package_bytes", 1),
                                    ("image_bytes", {}), ("capacity_inventory", {}), ("reset_postgres_counters", None),
                                    ("keystore_password", self.password), ("read_postgres", {})):
                    stack.enter_context(patch.object(runner, name, return_value=value))
                stack.enter_context(patch.object(runner, "kubelet_samples", return_value=None))
                record = runner.one({"name": "baseline", "duration_s": 60}, 50, root / "out", tester, 1)
                self.assert_private(json.dumps(record))
                self.assertTrue(any("load:" in error for error in record["errors"]))
                self.assertTrue(all(not path.exists() for path in directories))


class ProfileSelectionTests(unittest.TestCase):
    def paths(self):
        return sorted((runner.ROOT / "bench" / "configs").glob("*.yaml"))

    def test_default_all_preserves_every_config_including_explicit_skip(self):
        with patch.dict(os.environ, {}, clear=True):
            configs = runner.selected_configs(self.paths())
        self.assertEqual([config["name"] for config in configs],
                         [runner.load_config(path)["name"] for path in self.paths()])
        self.assertTrue(next(config for config in configs if config["name"] == "gc-serial")["skip"])

    def test_baseline_only_preserves_requested_client_counts_and_config(self):
        with patch.dict(os.environ, {"BENCH_PROFILE": "baseline", "BENCH_CLIENTS": "10,50"}):
            configs = runner.selected_configs(self.paths())
            self.assertEqual(configs, [runner.load_config(runner.ROOT / "bench/configs/baseline.yaml")])
            self.assertEqual(runner.selected_clients(configs[0]), [10, 50])
        self.assertFalse(configs[0]["restart"])

    def test_main_runs_only_selected_baseline_points(self):
        with patch.dict(os.environ, {"BENCH_PROFILE": "baseline", "BENCH_CLIENTS": "10,50"}), \
                patch.object(runner.shutil, "which", return_value="fixture-kubectl"), \
                patch.object(runner, "ready_age", return_value=(12, [])), \
                patch.object(runner, "snapshot", return_value={}) as snapshot, \
                patch.object(runner, "restore") as restore, \
                patch.object(runner, "one", return_value={"errors": []}) as one:
            self.assertEqual(runner.main([]), 0)
        self.assertEqual([(call.args[0]["name"], call.args[1]) for call in one.call_args_list],
                         [("baseline", 10), ("baseline-c50", 50)])
        snapshot.assert_called_once()
        restore.assert_called_once()

    def test_invalid_selector_exits_before_cluster_queries(self):
        with patch.dict(os.environ, {"BENCH_PROFILE": "unknown"}), patch.object(runner, "ready_age") as query:
            self.assertEqual(runner.main([]), 2)
        query.assert_not_called()

    def test_baseline_cannot_silently_run_nothing(self):
        with patch.dict(os.environ, {"BENCH_PROFILE": "baseline"}):
            with self.assertRaisesRegex(ValueError, "exactly one enabled baseline"):
                runner.selected_configs([])


def record(config, arch, rss, received, duration, mean, ready):
    return {
        "schema": 1,
        "arch": arch,
        "config": config,
        "git_sha": "fixture-revision",
        "kubelet": {"steady_rss_bytes": rss},
        "load": {
            "clients": 10,
            "messages_received": received,
            "duration_s": duration,
            "ping_pong_ms_mean": mean,
        },
        "time_to_ready": {"cold_s": ready, "warm_s": None},
        "errors": [],
    }


class BenchReportTests(unittest.TestCase):
    def test_different_loads_durations_and_revisions_do_not_dominate_each_other(self):
        for dimension in ("clients", "duration_s", "git_sha"):
            with self.subTest(dimension=dimension):
                slow = record("slow", "amd64", 20, 20, 60, 10, 20)
                fast = record("fast", "amd64", 10, 200, 60, 1, 10)
                if dimension == "git_sha":
                    fast["git_sha"] = "another-revision"
                else:
                    fast["load"][dimension] = 50 if dimension == "clients" else 120
                groups = report.cohorts([slow, fast])
                self.assertEqual([len(rows) for _label, rows in groups], [1, 1])
                text = report.markdown([slow, fast])
                self.assertIn("Front: slow", text)
                self.assertIn("Front: fast", text)
                self.assertNotIn("Dominated: slow", text)
                self.assertEqual(report.svg([slow, fast]).count("footprint vs throughput"), 2)

    def test_records_without_comparison_metadata_are_isolated(self):
        slow = record("slow", "amd64", 20, 20, 60, 10, 20)
        fast = record("fast", "amd64", 10, 200, 60, 1, 10)
        del slow["load"]["clients"]
        del fast["load"]["clients"]
        text = report.markdown([slow, fast])
        self.assertEqual(text.count("incomplete comparison metadata"), 2)
        self.assertNotIn("Dominated: slow", text)

    def test_cold_install_reference_is_not_ranked_against_warm_rollouts(self):
        cold = record("cold", "amd64", 20, 20, 60, 10, 120)
        warm = record("warm", "amd64", 10, 20, 60, 10, 120)
        warm["time_to_ready"]["warm_s"] = 12
        text = report.markdown([cold, warm])
        warm_view = text.split("#### footprint vs warm rollout time", 1)[1].split("###", 1)[0]
        self.assertIn("Front: warm", warm_view)
        self.assertNotIn("Front: cold", warm_view)
        self.assertIn("Cold install reference (s)", text)
        self.assertNotIn("footprint vs cold", text)
        self.assertNotIn("footprint vs cold", report.svg([cold, warm]))

    def test_startup_table_marks_invalid_and_missing_timings_without_rewriting_data(self):
        sample = record("baseline", "amd64", 20, 20, 60, 10, -1)
        sample["start_phases"] = {
            "takserver-messaging": {
                "image_pull_s": -61,
                "inits": [{"name": "wait-deps", "seconds": 22}],
                "jvm_to_log_s": 34.849,
                "log_to_ready_s": None,
            },
        }
        before = json.dumps(sample, sort_keys=True)
        text = report.markdown([sample])
        self.assertIn("invalid (-61)", text)
        self.assertIn("invalid (-1)", text)
        self.assertIn("wait-deps: 22.000", text)
        self.assertIn("34.849", text)
        self.assertIn("not measured", text)
        self.assertIsNone(report.point(sample)["cold_ready_s"])
        self.assertEqual(json.dumps(sample, sort_keys=True), before)

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
        self.assertIn("one scale per view", text)

    def test_both_architectures_share_the_footprint_axis(self):
        records = [
            record("baseline", "amd64", 100, 100, 10, 5, 20),
            record("heap", "amd64", 150, 80, 10, 6, 22),
            record("postgis", "amd64", 180, 90, 10, 7, 24),
            record("baseline", "arm64", 400, 100, 10, 5, 20),
            record("heap", "arm64", 450, 80, 10, 6, 22),
            record("postgis", "arm64", 480, 90, 10, 7, 24),
        ]
        first = report.svg(records).split("footprint vs mean latency", 1)[0]
        centers = {
            title: float(cx)
            for cx, _cy, title in re.findall(
                r'<circle cx="([0-9.]+)" cy="([0-9.]+)"[^>]*><title>([^<]+)</title>',
                first,
            )
        }
        self.assertEqual(
            [
                "amd64 baseline",
                "amd64 heap",
                "amd64 postgis",
                "arm64 baseline",
                "arm64 heap",
                "arm64 postgis",
            ],
            sorted(centers, key=centers.get),
        )


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
        "target=print_info_without_sending_to_cloud_watch_process,\n" * 2,
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


class CumulativeCounterTests(unittest.TestCase):
    def contract(self):
        root = runner.ROOT / "bench/fixtures/tester"
        source = (root / "tak_tester.py.txt").read_text()
        # Every guarded replacement must still match the actual pinned source.
        bound = tester_exit.bind_tester(source)
        namespace = {"time": time, "print_info_without_sending_to_cloud_watch_process": lambda *args: None}
        exec((root / "stats.py.txt").read_text(), namespace)
        namespace["stats"] = namespace["Stats"]()
        with patch.dict(os.environ, {"BENCH_CUMULATIVE_STATS": "1"}):
            exec(tester_exit.HELPER, namespace)
        return root, source, bound, namespace

    def test_real_startup_and_printer_explain_41_reports_for_50_clients(self):
        root, source, bound, namespace = self.contract()
        clock = [0.0]
        reports = []
        class Clock:
            @staticmethod
            def sleep(seconds):
                clock[0] += seconds
        class StopPrinter(Exception):
            pass
        def capture(*args):
            reports.append((clock[0], args[0]))
            raise StopPrinter
        printer_scope = {"time": Clock, "print": capture}
        exec((root / "printer.py.txt").read_text(), printer_scope)
        startup = next(node for node in ast.parse(source).body
                       if isinstance(node, ast.FunctionDef) and node.name == "test_streaming_cot")
        self.assertIn("time.sleep(offset)", ast.get_source_segment(source, startup))
        scheduled = []
        class Client:
            def __init__(self, **kwargs):
                self.arr = kwargs["arr"]
            def start(self):
                self.arr[2] += 1  # A fixture connection event, not a real server.
        class PrinterProcess:
            def __init__(self, target, args):
                self.args = args
            def start(self):
                scheduled.append((clock[0], self.args))
        class Manager:
            def dict(self):
                return {}
        startup_scope = {**namespace, "time": Clock, "Manager": Manager,
                         "PyTAKStreamingCotProcess": Client, "Process": PrinterProcess,
                         "print_info_without_sending_to_cloud_watch_process": None,
                         "print_data_dict": lambda data: "", "logger": type("Logger", (), {"info": staticmethod(lambda *args: None)})}
        # Execute the unmodified pinned startup body; return at its infinite
        # monitoring loop so the fixture itself never needs a live server.
        startup.body[-1] = ast.Return(value=ast.Constant(value=None))
        module = ast.fix_missing_locations(ast.Module(body=[startup], type_ignores=[]))
        exec(compile(module, "pinned-startup", "exec"), startup_scope)
        startup_scope["test_streaming_cot"]("fixture", 0, None, None, clients=50, offset=1)
        self.assertEqual(clock[0], 50)
        self.assertEqual(len(scheduled), 50)
        for arrival, args in scheduled:
            clock[0] = arrival
            try:
                printer_scope["print_info_without_sending_to_cloud_watch_process"](*args[:2], 20)
            except StopPrinter:
                pass
        self.assertEqual(sum(timestamp <= 60 for timestamp, _ in reports), 41)
        self.assertEqual(sum(arr[2] for arr in namespace["stats"].data.values()), 0)
        self.assertIn("target=_tak_tester_quiet_printer,", bound)

    def test_cumulative_snapshot_preserves_observed_events_without_reset_or_duplicates(self):
        _root, _source, _bound, namespace = self.contract()
        for index in range(50):
            arr = namespace["stats"].init_uid(str(index))
            arr[0], arr[1], arr[2], arr[5], arr[6] = 3, 2, 1, 2, 8
        output = io.StringIO()
        with patch.dict(os.environ, {"BENCH_CUMULATIVE_STATS": "1"}), contextlib.redirect_stdout(output):
            namespace["_tak_tester_quiet_printer"]("unused", [], 20)
            namespace["_tak_tester_emit_stats"]()
            namespace["_tak_tester_emit_stats"]()
        parsed = loadlog.parse(output.getvalue())
        self.assertEqual(parsed["connects"], 50)
        self.assertEqual(parsed["messages_sent"], 150)
        self.assertEqual(parsed["messages_received"], 100)
        self.assertEqual(parsed["ping_pong_ms_mean"], 4)
        self.assertEqual(len(output.getvalue().splitlines()), 50)
        self.assertEqual(sum(arr[2] for arr in namespace["stats"].data.values()), 50)

    def test_unbound_mode_retains_upstream_printer_and_drift_fails_closed(self):
        _root, source, _bound, namespace = self.contract()
        calls = []
        namespace["print_info_without_sending_to_cloud_watch_process"] = lambda *args: calls.append(args)
        with patch.dict(os.environ, {"BENCH_CUMULATIVE_STATS": "0"}):
            namespace["_tak_tester_quiet_printer"]("uid", [1], 20)
        self.assertEqual(calls, [("uid", [1], 20)])
        changed = source.replace("target=print_info_without_sending_to_cloud_watch_process,",
                                 "target=changed_printer,", 1)
        with self.assertRaisesRegex(RuntimeError, "offline metrics printer appeared 1 times"):
            tester_exit.bind_tester(changed)

    def test_requested_but_unconnected_clients_are_not_invented(self):
        _root, _source, _bound, namespace = self.contract()
        for index in range(50):
            namespace["stats"].init_uid(str(index))[2] = int(index < 41)
        output = io.StringIO()
        with patch.dict(os.environ, {"BENCH_CUMULATIVE_STATS": "1"}), contextlib.redirect_stdout(output):
            namespace["_tak_tester_emit_stats"]()
        self.assertEqual(loadlog.parse(output.getvalue())["connects"], 41)

    def test_snapshot_failure_is_invalid_evidence_and_still_stops_children(self):
        _root, _source, _bound, namespace = self.contract()
        class BusyLock:
            def acquire(self, timeout):
                return False
        class BusyArray:
            def get_lock(self):
                return BusyLock()
        namespace["stats"].data["busy"] = BusyArray()
        stopped = []
        namespace["_tak_tester_terminate_procs"] = lambda procs: stopped.extend(procs)
        output = io.StringIO()
        with patch.dict(os.environ, {"BENCH_CUMULATIVE_STATS": "1"}), contextlib.redirect_stdout(output):
            namespace["_tak_tester_stop_procs"](["client"])
        self.assertEqual(stopped, ["client"])
        with self.assertRaisesRegex(ValueError, "snapshot"):
            loadlog.parse(output.getvalue())


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


class StartPhaseTests(unittest.TestCase):
    def test_phases_split_pull_init_jvm_and_ready(self):
        pod = {
            "metadata": {"creationTimestamp": "2026-10-25T06:53:00Z"},
            "status": {
                "initContainerStatuses": [
                    {
                        "name": "wait-deps",
                        "state": {"terminated": {
                            "startedAt": "2026-10-25T06:53:05Z",
                            "finishedAt": "2026-10-25T06:53:20Z",
                        }},
                    },
                ],
                "containerStatuses": [
                    {"name": "api", "state": {"running": {"startedAt": "2026-10-25T06:53:21Z"}}},
                ],
                "conditions": [
                    {"type": "Ready", "status": "True", "lastTransitionTime": "2026-10-25T06:55:10Z"},
                ],
            },
        }
        events = [
            {"reason": "Pulling", "firstTimestamp": "not-a-time"},
            {"reason": "Pulling", "eventTime": "2026-10-25T06:53:01Z"},
            {"reason": "Pulled", "firstTimestamp": "2026-10-25T06:53:04Z"},
            {"reason": "Pulled", "firstTimestamp": "2026-10-25T06:53:09Z"},
        ]
        log = "noise\n2026-10-25T06:54:59.123456789Z Started TAK Server\n"
        got = phases.pod_phases(pod, events, log)
        self.assertEqual(got["image_pull_s"], 3.0)
        self.assertEqual(got["inits"], [{"name": "wait-deps", "seconds": 15.0}])
        self.assertEqual(got["container_to_log_s"], 98.123)
        self.assertIsNone(got["jvm_to_log_s"])
        self.assertEqual(got["log_to_ready_s"], 10.877)

    def test_pull_pairs_each_container_and_skips_present_images(self):
        def event(reason, stamp, path, field="firstTimestamp"):
            return {"reason": reason, field: stamp, "involvedObject": {"fieldPath": path}}

        init = "spec.initContainers{wait-deps}"
        main = "spec.containers{api}"
        # Out of time order, as kubectl returns them. The init image was
        # already present (Pulled without Pulling) before the main pull.
        events = [
            event("Pulled", "2026-11-03T09:50:40Z", main),
            event("Pulled", "2026-11-03T09:49:00Z", init),
            event("Pulling", "2026-11-03T09:50:01Z", main, field="eventTime"),
            {"reason": "Scheduled", "firstTimestamp": "2026-11-03T09:48:59Z"},
        ]
        self.assertEqual(phases.pod_phases({}, events, "")["image_pull_s"], 39.0)
        # Two real pulls add up.
        events += [
            event("Pulling", "2026-11-03T09:48:50Z", "spec.initContainers{import-trust}"),
            event("Pulled", "2026-11-03T09:48:55Z", "spec.initContainers{import-trust}"),
        ]
        self.assertEqual(phases.pod_phases({}, events, "")["image_pull_s"], 44.0)
        # Every image already present: no pull time, not zero.
        present = [event("Pulled", "2026-11-03T09:49:00Z", init), event("Pulled", "2026-11-03T09:49:30Z", main)]
        self.assertIsNone(phases.pod_phases({}, present, "")["image_pull_s"])

    def test_collection_keeps_early_marker_and_binds_events_to_pod_uid(self):
        pod = {"metadata": {"name": "api-1", "uid": "uid-1"},
               "spec": {"containers": [{"name": "api"}]},
               "status": {"containerStatuses": [{"name": "api", "state": {
                   "running": {"startedAt": "2026-10-25T00:00:00Z"}}}]}}
        calls = []
        def command(*args, **kwargs):
            calls.append((args, kwargs))
            self.assertEqual(kwargs["timeout"], 30)
            if args[0] == "logs":
                text = "2026-10-25T00:00:05Z Started TAK Server\n" + "noise\n" * 500
            elif args[1] == "events":
                self.assertIn("involvedObject.uid=uid-1", args)
                text = '{"items": []}'
            else:
                text = json.dumps({"items": [pod]})
            return subprocess.CompletedProcess(args, 0, stdout=text)
        with patch.object(runner, "kubectl", side_effect=command), patch.object(
                runner, "redacted_text", side_effect=lambda text: text):
            got, errors = runner.start_phases()
        self.assertEqual(errors, [])
        self.assertEqual(got["takserver-api"]["container_to_log_s"], 5)
        self.assertEqual(len(calls), 6)

    def test_evidence_tracks_selected_container_without_log_contents(self):
        pod = {"metadata": {"name": "api-1", "uid": "pod-uid"},
               "spec": {"containers": [{"name": "api"}]},
               "status": {"containerStatuses": [
                   {"name": "sidecar", "state": {"running": {"startedAt": "2026-10-25T00:00:00Z"}}},
                   {"name": "api", "containerID": "containerd://abc", "restartCount": 1,
                    "state": {"running": {"startedAt": "2026-10-25T00:00:05Z"}}}]}}
        got = phases.pod_phases(pod, [], "2026-10-25T00:00:08Z Started TAK Server secret-data")
        self.assertEqual(got["container_to_log_s"], 3)
        self.assertIsNone(got["jvm_to_log_s"])
        self.assertEqual(got["evidence"]["pod_uid"], "pod-uid")
        self.assertEqual(got["evidence"]["container_id"], "containerd://abc")
        self.assertEqual(got["evidence"]["restart_count"], 1)
        self.assertNotIn("secret-data", str(got))
        stale = phases.pod_phases(pod, [], "2026-10-25T00:00:01Z Started TAK Server")
        self.assertIsNone(stale["container_to_log_s"])
        self.assertIsNone(stale["evidence"]["startup_log_at"])
        self.assertIsNone(phases.elapsed(phases.parse_time("2026-10-25T00:00:05Z"),
                                         phases.parse_time("2026-10-25T00:00:01Z")))

    def test_missing_inputs_stay_unset(self):
        self.assertIsNone(phases.parse_time(None))
        self.assertIsNone(phases.parse_time("nope"))
        self.assertIsNone(phases.elapsed(None, phases.parse_time("2026-10-25T00:00:00Z")))
        self.assertIsNone(phases.first_log_time("", ("Started TAK Server",)))
        self.assertIsNone(phases.first_log_time("no stamp here Started TAK Server", ("Started TAK Server",)))
        self.assertIsNone(phases.first_log_time("2026-10-25T00:00:00Z other", ("Started TAK Server",)))
        got = phases.pod_phases({}, [], "")
        self.assertIsNone(got["image_pull_s"])
        self.assertEqual(got["inits"], [])
        self.assertIsNone(got["jvm_to_log_s"])
        self.assertIsNone(got["log_to_ready_s"])
        self.assertIsNone(phases.pod_phases(
            {"status": {"containerStatuses": [{"state": {}}]}},
            [{"reason": "Pulling"}],
            "2026-10-25T00:00:01Z Tomcat started on port 8443",
        )["jvm_to_log_s"])
class StartupShapeTests(unittest.TestCase):
    def test_generation_and_restarts_use_the_highest_count(self):
        generations = startup.max_generation([
            {"metadata": {"generation": 1}},
            {"metadata": {"generation": 2}},
            {"metadata": {}},
        ])
        restarts = startup.max_restarts([
            {"status": {"containerStatuses": [{"restartCount": 0}], "initContainerStatuses": [{"restartCount": 1}]}},
            {"status": {"containerStatuses": [{"restartCount": "nope"}]}},
        ])
        self.assertEqual(generations, 2)
        self.assertEqual(restarts, 1)
        self.assertIsNone(startup.max_generation([]))
        self.assertIsNone(startup.max_restarts([{"status": {}}]))


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

    def test_reset_clears_the_counters_the_query_reads(self):
        calls = []

        def fake(*args):
            calls.append(args)

            class Result:
                stdout = (
                    '{"items": [{"metadata": {"name": "takserver-postgresql-0"}}]}'
                    if args[:2] == ("get", "pods") else ""
                )

            return Result()

        runner.reset_postgres_counters(fake)
        psql = next(call for call in calls if "psql" in call)
        self.assertEqual(psql[psql.index("-d") + 1], "cot")
        self.assertIn("SELECT pg_stat_reset_shared('checkpointer')", psql)
        self.assertIn("SELECT pg_stat_reset_shared('io')", psql)
        self.assertIn("SELECT pg_stat_reset_shared('bgwriter')", psql)
        self.assertIn("pg_stat_checkpointer", runner.POSTGRES_QUERY)
        self.assertIn("d.datname = 'cot'", runner.POSTGRES_QUERY)

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


class RestoreTests(unittest.TestCase):
    CONFIG = {
        "name": "mixed",
        "env": [{
            "workload": "deployment/takserver-messaging",
            "namespace": "takserver",
            "container": "takserver-messaging",
            "name": "JDK_JAVA_OPTIONS",
            "value": "-Xms768m -Xmx768m",
        }],
        "resources": [{
            "workload": "deployment/takserver-api",
            "namespace": "takserver",
            "container": "takserver-api",
            "memory_request": "1536Mi",
            "memory_limit": "2Gi",
        }],
    }

    @staticmethod
    def fake(containers):
        calls = []

        class Result:
            def __init__(self, stdout=""):
                self.stdout = stdout

        def run(*args):
            calls.append(list(args))
            if args[0] == "get":
                spec = {"spec": {"template": {"spec": {"containers": containers[args[1]]}}}}
                return Result(json.dumps(spec))
            return Result()

        return run, calls

    def test_an_env_the_install_did_not_set_is_removed(self):
        run, calls = self.fake({
            "deployment/takserver-messaging": [{"name": "takserver-messaging", "env": [{"name": "A", "value": "1"}]}],
            "deployment/takserver-api": [{"name": "takserver-api", "resources": {"limits": {"memory": "1Gi"}}}],
        })
        saved = runner.snapshot(self.CONFIG, run)
        runner.restore(self.CONFIG, saved, run, wait=False)
        changes = [call for call in calls if call[0] != "get"]
        self.assertEqual(
            changes[0],
            ["set", "env", "deployment/takserver-messaging", "-n", "takserver",
             "-c", "takserver-messaging", "JDK_JAVA_OPTIONS-"],
        )
        patch = json.loads(changes[1][-1])
        resources = patch["spec"]["template"]["spec"]["containers"][0]["resources"]
        self.assertEqual(resources, {"requests": {"memory": None}, "limits": {"memory": "1Gi"}})

    def test_an_installed_env_value_is_put_back(self):
        run, _ = self.fake({
            "deployment/takserver-messaging": [{
                "name": "takserver-messaging",
                "env": [{"name": "JDK_JAVA_OPTIONS", "value": "-Dx=1"}],
            }],
            "deployment/takserver-api": [{"name": "takserver-api"}],
        })
        commands = runner.restore_commands(runner.snapshot(self.CONFIG, run))
        self.assertEqual(commands[0][-1], "JDK_JAVA_OPTIONS=-Dx=1")

    def test_value_from_is_refused(self):
        run, _ = self.fake({
            "deployment/takserver-messaging": [{
                "name": "takserver-messaging",
                "env": [{"name": "JDK_JAVA_OPTIONS", "valueFrom": {"configMapKeyRef": {}}}],
            }],
            "deployment/takserver-api": [{"name": "takserver-api"}],
        })
        with self.assertRaises(RuntimeError):
            runner.snapshot(self.CONFIG, run)


class RestartEvidenceTests(unittest.TestCase):
    def test_a_restart_still_fails_and_records_the_exit(self):
        text = runner.format_restart(
            "cloudtak-abc",
            [{
                "name": "cloudtak",
                "restartCount": 2,
                "lastState": {"terminated": {"reason": "Error", "exitCode": 1, "signal": 0}},
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
            }],
            {"cloudtak": "previous=Error: listen failed"},
        )
        self.assertIn("cloudtak-abc restarted, so this is not a cold start", text)
        self.assertIn("previous reason=Error exit=1 signal=0", text)
        self.assertIn("waiting=CrashLoopBackOff", text)
        self.assertIn("listen failed", text)

    def test_ready_age_redacts_the_previous_log_and_still_fails(self):
        pod = {
            "metadata": {"name": "cloudtak-abc"},
            "status": {"containerStatuses": [{
                "name": "cloudtak",
                "restartCount": 1,
                "lastState": {"terminated": {"reason": "Error", "exitCode": 137, "signal": 9}},
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
            }]},
        }

        class Result:
            def __init__(self, stdout, returncode=0):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = returncode

        def fake_kubectl(*args, check=True, timeout=None):
            if args[:2] == ("get", "pods") and args[3] == "takserver":
                return Result(json.dumps({"items": []}))
            if args[:2] == ("get", "pods") and args[3] == "cloudtak":
                return Result(json.dumps({"items": [pod]}))
            if args[0] == "logs":
                return Result('secret="restart-sentinel-value"\nError: listen failed\n')
            return Result("", returncode=1)

        original = runner.kubectl
        runner.kubectl = fake_kubectl
        try:
            age, errors = runner.ready_age()
        finally:
            runner.kubectl = original
        self.assertIsNone(age)
        joined = " ".join(errors)
        self.assertIn("restarted, so this is not a cold start", joined)
        self.assertIn("exit=137", joined)
        self.assertIn("signal=9", joined)
        self.assertNotIn("restart-sentinel-value", joined)
        self.assertIn("[REDACTED]", joined)
        self.assertIn("listen failed", joined)

    def test_log_timeout_discards_the_partial_stream(self):
        def expired(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(
                cmd="kubectl",
                timeout=30,
                output='secret="timeout-sentinel-value"\n'.encode("utf-8"),
            )

        original_run = runner.subprocess.run
        original_cmd = runner.kubectl_cmd
        runner.subprocess.run = expired
        runner.kubectl_cmd = lambda: ["kubectl"]
        try:
            text = runner._container_excerpt("cloudtak", "cloudtak-abc", "cloudtak")
        finally:
            runner.subprocess.run = original_run
            runner.kubectl_cmd = original_cmd
        self.assertIn("previous=timed out", text)
        self.assertIn("current=timed out", text)
        self.assertNotIn("timeout-sentinel-value", text)


if __name__ == "__main__":
    unittest.main()
