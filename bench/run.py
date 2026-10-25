#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Run one benchmark sweep against a cluster that is already up.

Writes bench/out/<arch>/<config>.json. A field that was not measured is null
and listed in errors. This script does not fill those fields with zero.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# Running this file as a script puts bench/ on sys.path and hides the package.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.loadlog import parse
from bench.startup import max_generation, max_restarts
from bench.tester_exit import bind_tester, reap

UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "k": 10**3, "M": 10**6, "G": 10**9}


def kubectl_cmd():
    if shutil.which("kubectl"):
        return ["kubectl"]
    if shutil.which("uds"):
        return ["uds", "zarf", "tools", "kubectl"]
    raise RuntimeError("kubectl is not available")


def kubectl(*args, check=True):
    result = subprocess.run([*kubectl_cmd(), *args], check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        command = " ".join(str(part) for part in result.args)
        if detail:
            raise RuntimeError(f"{command}: {detail}")
        raise RuntimeError(f"{command} exited {result.returncode}")
    return result


def quantity(value):
    if not value:
        return None
    if value.endswith("m") and value[:-1].isdigit():
        return None
    for suffix, factor in UNITS.items():
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * factor)
    return int(value)


def cpu_millis(value):
    if not value:
        return None
    if value.endswith("m"):
        return int(float(value[:-1]))
    return int(float(value) * 1000)


def arch_name():
    machine = platform.machine()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


def load_config(path):
    with open(path, encoding="utf-8") as handle:
        body = yaml.safe_load(handle)
    if not isinstance(body, dict) or not body.get("name"):
        raise SystemExit(f"{path} has no name")
    return body


def selected_clients(config):
    raw = os.environ.get("BENCH_CLIENTS", "10")
    if raw == "all":
        return [int(item) for item in config["clients"]]
    return [int(item) for item in raw.split(",") if item.strip()]


def footprint():
    errors = []
    cpu_req = mem_req = cpu_lim = mem_lim = 0
    limits_complete = True
    cpu_limits_complete = True
    for namespace in ("takserver", "cloudtak"):
        try:
            raw = kubectl("get", "pods", "-n", namespace, "-o", "json").stdout
        except (RuntimeError, subprocess.CalledProcessError) as error:
            errors.append(f"{namespace}: {error}")
            continue
        for pod in json.loads(raw).get("items", []):
            if pod.get("status", {}).get("phase") != "Running":
                continue
            for container in pod["spec"].get("containers", []):
                resources = container.get("resources", {})
                requests = resources.get("requests", {})
                limits = resources.get("limits", {})
                cpu = cpu_millis(requests.get("cpu"))
                memory = quantity(requests.get("memory"))
                if cpu is None or memory is None:
                    errors.append(f"{namespace}/{pod['metadata']['name']}/{container['name']} has no request")
                else:
                    cpu_req += cpu
                    mem_req += memory
                cpu_limit = cpu_millis(limits.get("cpu"))
                memory_limit = quantity(limits.get("memory"))
                if cpu_limit is None:
                    cpu_limits_complete = False
                else:
                    cpu_lim += cpu_limit
                if memory_limit is None:
                    limits_complete = False
                else:
                    mem_lim += memory_limit
    return {
        "cpu_requests_m": cpu_req,
        "memory_requests_bytes": mem_req,
        "cpu_limits_m": cpu_lim if cpu_limits_complete else None,
        "memory_limits_bytes": mem_lim if limits_complete else None,
    }, errors


def startup_shape():
    """Generation and restarts for the four TAK Deployments. Null when unread."""
    errors = []
    try:
        raw = kubectl("get", "deploy", "-n", "takserver", "-o", "json").stdout
        pods = kubectl(
            "get", "pods", "-n", "takserver",
            "-l", "app in (takserver-api,takserver-messaging,takserver-config,takserver-plugins)",
            "-o", "json",
        ).stdout
    except (RuntimeError, subprocess.CalledProcessError) as error:
        return {"max_generation": None, "max_restart_count": None}, [str(error)]
    try:
        generations = max_generation(json.loads(raw).get("items", []))
        restarts = max_restarts(json.loads(pods).get("items", []))
    except json.JSONDecodeError as error:
        return {"max_generation": None, "max_restart_count": None}, [f"startup: {error}"]
    if generations is None:
        errors.append("no TAK deployment generation")
    if restarts is None:
        errors.append("no TAK container restart count")
    return {"max_generation": generations, "max_restart_count": restarts}, errors


def ready_age():
    """Seconds from pod creation to Ready. Null when a pod has restarted."""
    ages = []
    errors = []
    for namespace, selector in (
        ("takserver", "app in (takserver-api,takserver-messaging,takserver-config)"),
        ("cloudtak", "app=cloudtak"),
    ):
        try:
            raw = kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json").stdout
        except (RuntimeError, subprocess.CalledProcessError) as error:
            errors.append(str(error))
            continue
        for pod in json.loads(raw).get("items", []):
            statuses = pod.get("status", {}).get("containerStatuses") or []
            if any(status.get("restartCount", 0) for status in statuses):
                errors.append(f"{pod['metadata']['name']} restarted, so this is not a cold start")
                return None, errors
            created = pod["metadata"].get("creationTimestamp")
            ready = next(
                (
                    condition.get("lastTransitionTime")
                    for condition in pod.get("status", {}).get("conditions", [])
                    if condition.get("type") == "Ready" and condition.get("status") == "True"
                ),
                None,
            )
            if not created or not ready:
                errors.append(f"{pod['metadata']['name']} has no Ready time")
                return None, errors
            start = datetime.fromisoformat(created.replace("Z", "+00:00"))
            done = datetime.fromisoformat(ready.replace("Z", "+00:00"))
            ages.append((done - start).total_seconds())
    if not ages:
        errors.append("no Ready pods to time")
        return None, errors
    return max(ages), errors


def apply_config(config):
    for item in config.get("env") or []:
        kubectl(
            "set", "env", item["workload"], "-n", item["namespace"],
            "-c", item["container"], f"{item['name']}={item['value']}",
        )
    for item in config.get("resources") or []:
        kubectl(
            "set", "resources", item["workload"], "-n", item["namespace"],
            "-c", item["container"],
            f"--requests=memory={item['memory_request']}",
            f"--limits=memory={item['memory_limit']}",
        )


def rollout(config):
    started = time.monotonic()
    seen = False
    for item in (config.get("env") or []) + (config.get("resources") or []):
        kubectl("rollout", "restart", item["workload"], "-n", item["namespace"])
        kubectl("rollout", "status", item["workload"], "-n", item["namespace"], "--timeout=600s")
        seen = True
    if not seen:
        return None
    return round(time.monotonic() - started, 3)


def keystore_password():
    try:
        encoded = kubectl(
            "get", "secret", "takserver-keystore", "-n", "takserver",
            "-o", "jsonpath={.data.CAPASS}",
        ).stdout.strip()
    except (RuntimeError, subprocess.CalledProcessError):
        encoded = ""
    if encoded:
        import base64
        return base64.b64decode(encoded).decode()
    # This branch still issues certificates with the upstream example password.
    return "atakatak"


def kubelet_samples(stop, sink, errors):
    while not stop.is_set():
        try:
            nodes = kubectl("get", "nodes", "-o", "name").stdout.split()
            rss = cpu = 0
            found = False
            for node in nodes:
                raw = kubectl("get", "--raw", f"/api/v1/nodes/{node.split('/', 1)[-1]}/proxy/stats/summary").stdout
                for pod in json.loads(raw).get("pods", []):
                    if pod.get("podRef", {}).get("namespace") not in ("takserver", "cloudtak"):
                        continue
                    for container in pod.get("containers", []):
                        memory = container.get("memory", {}).get("workingSetBytes")
                        usage = container.get("cpu", {}).get("usageNanoCores")
                        if memory is None or usage is None:
                            continue
                        found = True
                        rss += memory
                        cpu += usage
            if found:
                sink.append({"rss": rss, "cpu": cpu})
            else:
                errors.append("kubelet summary had no TAK or CloudTAK stats")
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            errors.append(f"kubelet summary: {error}")
        stop.wait(5)


def run_load(clients, duration, password, tester):
    if not tester.is_file():
        raise RuntimeError(f"load tester is not at {tester}")
    cert_dir = Path(tempfile.mkdtemp(prefix="bench-certs-"))
    try:
        subprocess.run(["bash", str(ROOT / "tests" / "extract-certs.sh"), str(cert_dir)], check=True, cwd=ROOT)
        p12 = cert_dir / "admin.p12"
        subprocess.run(
            [
                "openssl", "pkcs12", "-export",
                "-in", str(cert_dir / "admin.pem"),
                "-inkey", str(cert_dir / "admin.key"),
                "-passin", f"pass:{password}",
                "-passout", f"pass:{password}",
                "-out", str(p12),
            ],
            check=True,
            capture_output=True,
        )
        forward = subprocess.Popen(
            [*kubectl_cmd(), "port-forward", "-n", "istio-passthrough-gateway",
             "svc/passthrough-ingressgateway", "18089:8089"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        time.sleep(2)
        # --send-metrics is omitted on purpose. The tester declares it as
        # type=bool, and argparse treats every present string as true.
        # Without a config file, mission_api_config is set only when
        # --skip-mission-api is passed. Otherwise the process exits before
        # any client starts. The printer sleeps for --send-metrics-interval
        # before the first line, so that interval has to land inside duration.
        interval = max(1, duration // 3)
        patched_dir = Path(tempfile.mkdtemp(prefix="bench-tester-"))
        patched = patched_dir / "tak_tester.py"
        patched.write_text(bind_tester(tester.read_text(encoding="utf-8")), encoding="utf-8")
        env = os.environ.copy()
        env["TAK_TESTER_DURATION"] = str(duration)
        env["PYTHONPATH"] = str(tester.parent) + os.pathsep + env.get("PYTHONPATH", "")
        command = [
            sys.executable, "-u", str(patched),
            "--test-pytak", "--tls", "18089", "--host", "127.0.0.1",
            "--cert", str(p12), "--password", password,
            "--clients", str(clients), "--ping", "true",
            "--skip-mission-api",
            "--send-metrics-interval", str(interval),
        ]
        # New session so the client processes share a group we can kill.
        # The patched tester exits at TAK_TESTER_DURATION. reap is the
        # hard stop when a child join still outlives that deadline.
        proc = subprocess.Popen(
            command,
            cwd=tester.parent,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            text = reap(proc, duration + 20)
        finally:
            if forward.poll() is None:
                forward.terminate()
                try:
                    forward.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forward.kill()
                    forward.wait(timeout=5)
            shutil.rmtree(patched_dir, ignore_errors=True)
        try:
            return parse(text)
        except ValueError as error:
            tail = "\n".join(text.splitlines()[-12:])
            if tail:
                raise ValueError(f"{error}\n{tail}") from error
            raise
    finally:
        shutil.rmtree(cert_dir, ignore_errors=True)


def git_sha():
    # The benchmark job trims git off the runner to free disk. Actions still
    # exports GITHUB_SHA for the commit under test.
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def blank(arch, config, clients, duration):
    return {
        "schema": 1,
        "arch": arch,
        "config": config,
        "git_sha": git_sha(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "footprint": None,
        "kubelet": None,
        "images": None,
        "package_bytes": None,
        "time_to_ready": {"cold_s": None, "warm_s": None},
        "startup": {"max_generation": None, "max_restart_count": None},
        "load": {
            "clients": clients,
            "duration_s": duration,
            "messages_sent": None,
            "messages_received": None,
            "connects": None,
            "disconnects": None,
            "pong_count": None,
            "ping_pong_ms_sum": None,
            "ping_pong_ms_mean": None,
            "p95_ms": None,
        },
        "ci": {"wall_clock_s": None},
        "errors": [],
    }


def package_bytes():
    matches = sorted(ROOT.glob("zarf-package-takserver-*.tar.zst"))
    if not matches:
        return None
    return matches[-1].stat().st_size


def image_refs(text):
    refs = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        candidate = stripped[2:].split("#", 1)[0].strip().strip('"').strip("'")
        if " " in candidate or candidate.count("/") < 1 or ":" not in candidate:
            continue
        if "://" in candidate:
            continue
        refs.append(candidate)
    return refs


def manifest_command(image, arch, which=shutil.which):
    platform_name = f"linux/{arch}"
    crane = which("crane")
    if crane:
        return [crane, "--platform", platform_name, "manifest", image]
    uds = which("uds")
    if uds:
        return [uds, "zarf", "tools", "registry", "--platform", platform_name, "manifest", image]
    raise RuntimeError("crane is not installed and uds is not on PATH")


def image_bytes():
    images = image_refs((ROOT / "zarf.yaml").read_text(encoding="utf-8"))
    if not images:
        raise RuntimeError("zarf.yaml listed no images")
    seen = {}
    total = 0
    for image in images:
        manifest = json.loads(subprocess.check_output(manifest_command(image, arch_name()), text=True))
        layers = manifest.get("layers") or []
        if manifest.get("mediaType", "").endswith("list") or "manifests" in manifest:
            raise RuntimeError(f"{image} is an index; the manifest command did not return one platform")
        for layer in layers:
            size = layer.get("size")
            digest = layer.get("digest")
            if size is None or not digest:
                raise RuntimeError(f"{image} layer has no size")
            total += size
            seen[digest] = size
    return {"sum_bytes": total, "unique_bytes": sum(seen.values())}


def write_record(record, out_dir):
    dest = out_dir / record["arch"] / f"{record['config']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return dest


def one(config, clients, out_dir, tester, cold):
    duration = int(config["duration_s"])
    record = blank(arch_name(), config["name"], clients, duration)
    try:
        apply_config(config)
        if config.get("restart"):
            record["time_to_ready"]["warm_s"] = rollout(config)
            record["time_to_ready"]["cold_s"] = cold
        else:
            record["time_to_ready"]["cold_s"] = cold
        fp, fp_errors = footprint()
        record["footprint"] = fp
        record["errors"].extend(fp_errors)
        shape, shape_errors = startup_shape()
        record["startup"] = shape
        record["errors"].extend(shape_errors)
        record["package_bytes"] = package_bytes()
        if record["package_bytes"] is None:
            record["errors"].append("no zarf-package-takserver tarball to stat")
        try:
            record["images"] = image_bytes()
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            record["errors"].append(f"image bytes: {error}")
        samples = []
        sample_errors = []
        stop = threading.Event()
        thread = threading.Thread(target=kubelet_samples, args=(stop, samples, sample_errors), daemon=True)
        thread.start()
        try:
            password = keystore_password()
            parsed = run_load(clients, duration, password, tester)
            record["load"].update(parsed)
        except (RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as error:
            record["errors"].append(f"load: {error}")
        finally:
            stop.set()
            thread.join(timeout=10)
        record["errors"].extend(sample_errors)
        if samples:
            record["kubelet"] = {
                "peak_rss_bytes": max(item["rss"] for item in samples),
                "steady_rss_bytes": samples[-1]["rss"],
                "peak_cpu_nanocores": max(item["cpu"] for item in samples),
                "steady_cpu_nanocores": samples[-1]["cpu"],
            }
        else:
            record["errors"].append("no kubelet samples")
    except (RuntimeError, subprocess.CalledProcessError) as error:
        record["errors"].append(str(error))
    path = write_record(record, out_dir)
    print(f"wrote {path}")
    return record


def main(argv):
    config_dir = ROOT / "bench" / "configs"
    out_dir = ROOT / "bench" / "out"
    tester = Path(os.environ.get("TAK_LOAD_TESTER", ROOT / "upstream" / "takserver" / "src" / "testing" / "load_test" / "tak_tester.py"))
    if not shutil.which("kubectl") and not shutil.which("uds"):
        print("kubectl is not available, so no benchmark record was written", file=sys.stderr)
        return 2
    cold, cold_errors = ready_age()
    failed = False
    configs = sorted(config_dir.glob("*.yaml"))
    if not configs:
        print("no bench configs", file=sys.stderr)
        return 2
    for path in configs:
        original = load_config(path)
        if original.get("skip"):
            reason = original.get("reason") or "skipped"
            print(f"skip {original['name']}: {reason}")
            continue
        counts = selected_clients(original)
        for index, clients in enumerate(counts):
            # The first client count keeps the config name. Further counts
            # get a suffix so they do not overwrite that file.
            name = original["name"] if index == 0 else f"{original['name']}-c{clients}"
            record = one({**original, "name": name}, clients, out_dir, tester, cold)
            if cold_errors and not original.get("restart"):
                record["errors"].extend(cold_errors)
                write_record(record, out_dir)
            if record["errors"]:
                failed = True
                print(f"{name}: " + "; ".join(record["errors"]), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
