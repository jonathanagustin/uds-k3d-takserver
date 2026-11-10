#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Run one benchmark sweep against a cluster that is already up.

Writes bench/out/<arch>/<config>.json. A field that was not measured is null
and listed in errors. This script does not fill those fields with zero.
"""

import base64
import json
import os
import platform
import re
import importlib.util
import resource
import signal
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
from bench import capacity, sustained
from bench.phases import pod_phases
from bench.startup import max_generation, max_restarts
from bench.tester_exit import ANCHOR, bind_tester, reap, kill_group

UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "k": 10**3, "M": 10**6, "G": 10**9}
POSTGRES_SETTINGS = (
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "max_wal_size",
    "checkpoint_timeout",
)
_SETTING_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
_SETTING_VALUE = re.compile(r"^[0-9]+(kB|MB|GB|ms|s|min)?$")
# Set when this process has applied ALTER SYSTEM. A later config resets it.
_postgres_custom = False
# PostgreSQL 17 moved the checkpoint counters from pg_stat_bgwriter to
# pg_stat_checkpointer and dropped buffers_backend; client backend writes
# are in pg_stat_io. The TAK server runs PostgreSQL 18.
POSTGRES_QUERY = """
SELECT json_build_object(
  'blks_hit', d.blks_hit,
  'blks_read', d.blks_read,
  'temp_files', d.temp_files,
  'temp_bytes', d.temp_bytes,
  'checkpoints_timed', c.num_timed,
  'checkpoints_req', c.num_requested,
  'checkpoint_write_ms', c.write_time,
  'checkpoint_sync_ms', c.sync_time,
  'buffers_backend', (
    SELECT COALESCE(sum(io.writes), 0)::bigint
    FROM pg_stat_io io
    WHERE io.backend_type = 'client backend'
  ),
  'stats_reset_database', d.stats_reset,
  'stats_reset_checkpointer', c.stats_reset,
  'stats_reset_io', (SELECT max(io.stats_reset) FROM pg_stat_io io WHERE io.backend_type = 'client backend'),
  'shared_buffers', current_setting('shared_buffers'),
  'work_mem', current_setting('work_mem'),
  'effective_cache_size', current_setting('effective_cache_size'),
  'max_wal_size', current_setting('max_wal_size'),
  'checkpoint_timeout', current_setting('checkpoint_timeout')
)
FROM pg_stat_database d
CROSS JOIN pg_stat_checkpointer c
WHERE d.datname = 'cot'
""".strip()


def kubectl_cmd():
    if shutil.which("kubectl"):
        return ["kubectl", "--context", "k3d-uds"] if sustained.enabled() else ["kubectl"]
    if shutil.which("uds"):
        return ["uds", "zarf", "tools", "kubectl", "--context", "k3d-uds"] if sustained.enabled() else ["uds", "zarf", "tools", "kubectl"]
    raise RuntimeError("kubectl is not available")


def kubectl(*args, check=True, timeout=None):
    if sustained.enabled() and timeout is None:
        timeout = 15
    try:
        result = subprocess.run(
            [*kubectl_cmd(), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Drop any partial stream. It was cut off before redaction.
        if check:
            raise RuntimeError(f"kubectl timed out after {timeout}s")
        return subprocess.CompletedProcess(list(args), 124, stdout="", stderr="")
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


def selected_configs(paths):
    profile = os.environ.get("BENCH_PROFILE", "all")
    if profile not in ("all", "baseline"):
        raise ValueError("BENCH_PROFILE must be all or baseline")
    configs = [load_config(path) for path in paths]
    if profile == "baseline":
        configs = [config for config in configs if config["name"] == "baseline"]
        if len(configs) != 1 or configs[0].get("skip"):
            raise ValueError("baseline profile requires exactly one enabled baseline config")
    return configs


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


def redacted_text(text, tail=None):
    """Redact a complete log, then optionally keep the last lines.

    Truncating first can leave a fragment of a multiline secret with nothing
    for the redactor to match. A stream that cannot be redacted is not returned.
    """
    script = ROOT / ".github" / "scripts" / "redact-logs.py"
    raw = text.encode("utf-8", errors="replace") if isinstance(text, str) else (text or b"")
    try:
        result = subprocess.run(
            [sys.executable, str(script), "-"],
            input=raw,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "omitted: unsanitizable stream"
    if result.returncode != 0:
        return "omitted: unsanitizable stream"
    body = result.stdout.decode("utf-8", errors="replace")
    if tail is None:
        return body
    return "\n".join(body.splitlines()[-tail:])


def start_phases():
    """Pull, init, container start, and Ready for messaging and the API. Missing stays None."""
    found = {}
    errors = []
    for app in ("takserver-messaging", "takserver-api"):
        try:
            raw = kubectl("get", "pods", "-n", "takserver", "-l", f"app={app}", "-o", "json", timeout=30).stdout
            pods = json.loads(raw).get("items", [])
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            found[app] = None
            errors.append(f"{app} phases: {error}")
            continue
        if not pods:
            found[app] = None
            errors.append(f"{app} phases: no pod")
            continue
        pod = pods[0]
        name = pod.get("metadata", {}).get("name", "")
        events = []
        log_text = ""
        try:
            event_raw = kubectl(
                "get", "events", "-n", "takserver",
                "--field-selector", f"involvedObject.uid={pod.get('metadata', {}).get('uid', '')}",
                "-o", "json", timeout=30,
            ).stdout
            events = json.loads(event_raw).get("items", [])
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError):
            events = []
        containers = pod.get("spec", {}).get("containers") or []
        container = containers[0]["name"] if containers else app
        try:
            log_text = redacted_text(
                kubectl("logs", "-n", "takserver", name, "-c", container, "--timestamps", timeout=30).stdout,
            )
        except (RuntimeError, subprocess.CalledProcessError):
            log_text = ""
        found[app] = pod_phases(pod, events, log_text)
    return found, errors


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


def termination_summary(status):
    """Exit and signal from a container status. No log text."""
    last = (status.get("lastState") or {}).get("terminated") or {}
    state = status.get("state") or {}
    current = state.get("terminated") or {}
    waiting = state.get("waiting") or {}
    bits = [
        f"container={status.get('name') or 'unknown'}",
        f"restarts={status.get('restartCount', 0)}",
    ]
    if last:
        bits.append(
            "previous reason={reason} exit={exit} signal={signal}".format(
                reason=last.get("reason"),
                exit=last.get("exitCode"),
                signal=last.get("signal"),
            )
        )
    if current:
        bits.append(
            "current reason={reason} exit={exit} signal={signal}".format(
                reason=current.get("reason"),
                exit=current.get("exitCode"),
                signal=current.get("signal"),
            )
        )
    if waiting.get("reason"):
        bits.append(f"waiting={waiting.get('reason')}")
    return " ".join(bits)


def format_restart(pod_name, statuses, logs_by_container):
    """Cold-start failure text. A restart is still a failure.

    logs_by_container values must already be redacted. This function does not
    decide that a restart is acceptable.
    """
    parts = [f"{pod_name} restarted, so this is not a cold start"]
    for status in statuses:
        if not status.get("restartCount", 0):
            continue
        parts.append(termination_summary(status))
        name = status.get("name") or ""
        excerpt = (logs_by_container.get(name) or "").strip()
        if excerpt:
            parts.append(name + " log: " + excerpt)
    return "; ".join(parts)


# A dead API server can leave kubectl logs blocked. This is only the
# cold-start diagnostic, so give up and keep the exit fields.
_LOG_TIMEOUT_S = 30


def _container_excerpt(namespace, pod_name, container):
    """Redacted tail of the previous log, then the current log."""
    excerpts = []
    for label, extra in (("previous", ["--previous"]), ("current", [])):
        result = kubectl(
            "logs", "-n", namespace, pod_name, "-c", container, *extra,
            check=False, timeout=_LOG_TIMEOUT_S,
        )
        if result.returncode == 124:
            excerpts.append(f"{label}=timed out")
            continue
        body = result.stdout or ""
        if result.returncode != 0 and not body.strip():
            excerpts.append(f"{label}=unreadable")
            continue
        excerpts.append(label + "=" + redacted_text(body, tail=20).replace("\n", " | "))
    return " ".join(excerpts)


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
                name = pod.get("metadata", {}).get("name") or "unknown"
                logs = {}
                for status in statuses:
                    if not status.get("restartCount", 0):
                        continue
                    container = status.get("name") or ""
                    if not container:
                        continue
                    try:
                        logs[container] = _container_excerpt(namespace, name, container)
                    except (RuntimeError, OSError) as error:
                        logs[container] = f"unreadable: {error.__class__.__name__}"
                errors.append(format_restart(name, statuses, logs))
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


def postgres_statements(settings):
    """RESET ALL, then one ALTER SYSTEM per setting. Values are units only."""
    if not isinstance(settings, dict):
        raise RuntimeError("postgres settings must be a mapping")
    lines = ["ALTER SYSTEM RESET ALL"]
    for key in sorted(settings):
        value = str(settings[key])
        if _SETTING_NAME.match(key) is None or _SETTING_VALUE.match(value) is None:
            raise RuntimeError(f"refusing postgres setting {key}={value}")
        lines.append(f"ALTER SYSTEM SET {key} = '{value}'")
    return lines


def postgres_pod(runner):
    result = runner(
        "get", "pods", "-n", "takserver",
        "-l", "app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary",
        "-o", "json",
    )
    pods = [
        pod for pod in json.loads(result.stdout).get("items", [])
        if not pod.get("metadata", {}).get("deletionTimestamp")
    ]
    if len(pods) != 1:
        raise RuntimeError(f"expected one PostgreSQL pod, found {len(pods)}")
    return pods[0]["metadata"]["name"]


def postgres_sql(statements, runner, database="postgres"):
    # One -c each. psql wraps several statements in a single -c in one
    # transaction, and ALTER SYSTEM cannot run inside a transaction block.
    pod = postgres_pod(runner)
    args = [
        "exec", "-n", "takserver", pod, "-c", "postgresql",
        "--", "psql", "-X", "-w", "-U", "postgres", "-d", database,
        "-v", "ON_ERROR_STOP=1", "-At",
    ]
    for statement in statements:
        args.extend(["-c", statement])
    result = runner(*args)
    return result.stdout.strip()


def apply_postgres(config, runner=None):
    """Apply bench GUC overrides. Returns true when the server must restart."""
    global _postgres_custom
    settings = config.get("postgres") or {}
    if not settings and not _postgres_custom:
        return False
    run = runner or kubectl
    postgres_sql(postgres_statements(settings), run)
    _postgres_custom = bool(settings)
    return True


# pg_stat_reset() clears only the database it runs in, so it runs in cot,
# the database POSTGRES_QUERY reads. On PostgreSQL 17 and later the checkpoint
# counters are in pg_stat_checkpointer, which the 'bgwriter' reset no longer
# clears, and buffers_backend comes from pg_stat_io. Each target exists on
# PostgreSQL 17 and 18.
RESET_STATEMENTS = (
    "SELECT pg_stat_reset()",
    "SELECT pg_stat_reset_shared('bgwriter')",
    "SELECT pg_stat_reset_shared('checkpointer')",
    "SELECT pg_stat_reset_shared('io')",
)


def postgres_version():
    raw = postgres_sql(["SELECT json_build_object('server_version_num', current_setting('server_version_num'), 'postgis_version', postgis_lib_version())"], kubectl, database='cot')
    value = json.loads(raw)
    if (not re.fullmatch(r'18[0-9]{4}', value.get('server_version_num', ''))
            or not re.fullmatch(r'3\.6\.[0-9]+', value.get('postgis_version', ''))):
        raise ValueError('synthetic study requires PostgreSQL18 and PostGIS3.6')
    return value


def postgres_cgroup():
    pod = postgres_pod(kubectl)
    values = {}
    for name, pattern in (('memory.max', r'[0-9]+'), ('cpu.max', r'(?:max|[0-9]+) [0-9]+')):
        raw = kubectl('exec', '-n', 'takserver', pod, '-c', 'postgresql', '--',
                      'cat', '/sys/fs/cgroup/' + name).stdout.strip()
        if not re.fullmatch(pattern, raw):
            raise RuntimeError('PostgreSQL cgroup-v2 limit unavailable')
        values[name] = raw
    if values['memory.max'] != str(512 * 1024**2):
        raise RuntimeError('PostgreSQL cgroup memory limit differs from 512Mi study constraint')
    return values


def reset_postgres_counters(runner=None):
    run = runner or kubectl
    postgres_sql(list(RESET_STATEMENTS), run, database="cot")


def hit_ratio(hits, reads):
    total = hits + reads
    if total == 0:
        return None
    return round(hits / total, 6)


def assemble_postgres(row, rss_samples):
    if not isinstance(row, dict):
        raise RuntimeError("postgres stats were not a JSON object")
    needed = (
        "blks_hit", "blks_read", "temp_files", "temp_bytes",
        "checkpoints_timed", "checkpoints_req", "checkpoint_write_ms",
        "checkpoint_sync_ms", "buffers_backend",
    )
    for key in needed:
        if key not in row:
            raise RuntimeError(f"postgres stats missing {key}")
    samples = list(rss_samples or [])
    return {
        "datname": "cot",
        "blks_hit": row["blks_hit"],
        "blks_read": row["blks_read"],
        "hit_ratio": hit_ratio(row["blks_hit"], row["blks_read"]),
        "temp_files": row["temp_files"],
        "temp_bytes": row["temp_bytes"],
        "checkpoints_timed": row["checkpoints_timed"],
        "checkpoints_req": row["checkpoints_req"],
        "checkpoint_write_ms": row["checkpoint_write_ms"],
        "checkpoint_sync_ms": row["checkpoint_sync_ms"],
        "buffers_backend": row["buffers_backend"],
        "peak_rss_bytes": max(samples) if samples else None,
        "steady_rss_bytes": samples[-1] if samples else None,
        "settings": {key: row.get(key) for key in POSTGRES_SETTINGS},
        "stats_reset": {key: row[key] for key in ("stats_reset_database", "stats_reset_checkpointer", "stats_reset_io") if key in row},
    }


def read_postgres(rss_samples, runner=None):
    run = runner or kubectl
    raw = postgres_sql([POSTGRES_QUERY], run)
    if not raw:
        raise RuntimeError("postgres stats query returned no row")
    return assemble_postgres(json.loads(raw), rss_samples)


def rollout_items(config, postgres_changed):
    items = list(config.get("env") or []) + list(config.get("resources") or [])
    if postgres_changed:
        items.append({
            "workload": "statefulset/takserver-postgresql",
            "namespace": "takserver",
        })
    chosen = []
    seen = set()
    for item in items:
        key = (item["workload"], item["namespace"])
        if key in seen:
            continue
        seen.add(key)
        chosen.append(item)
    return chosen


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


def diagnose(namespace, workload):
    """What a timed-out rollout was waiting on. The nightly keeps no cluster."""
    lines = [f"--- {workload} in {namespace} did not finish rolling out"]
    pods = kubectl("get", "pods", "-n", namespace, "-o", "wide", check=False)
    lines.append(redacted_text(pods.stdout.strip() or pods.stderr.strip()))
    events = kubectl(
        "get", "events", "-n", namespace, "--sort-by=.lastTimestamp", check=False,
    )
    lines.append(redacted_text(events.stdout.strip() or events.stderr.strip(), tail=25))
    if workload.startswith("deployment/"):
        for container, tail in (("wait-deps", 40), (workload.split("/", 1)[1], 80)):
            logs = kubectl(
                "logs", workload, "-n", namespace, "-c", container, check=False,
            )
            text = redacted_text(logs.stdout.strip() or logs.stderr.strip(), tail=tail)
            lines.append(f"--- {container} logs")
            lines.append(text)
    print("\n".join(lines), file=sys.stderr)


def pod_container(workload, namespace, container, runner):
    result = runner("get", workload, "-n", namespace, "-o", "json")
    spec = json.loads(result.stdout)
    for item in spec["spec"]["template"]["spec"].get("containers", []):
        if item["name"] == container:
            return item
    raise RuntimeError(f"{workload} in {namespace} has no container {container}")


def snapshot(config, runner=None):
    """The installed env values and memory a config is about to change.

    apply_config edits the live workloads, and nothing put them back, so one
    config's changes carried into every config after it. heap-768 left
    JDK_JAVA_OPTIONS=-Xms768m on messaging. enable_admin.sh runs
    java -Xmx128m UserManager.jar, which then exits with "Initial heap size set
    to a larger value than the maximum heap size", the admin user is never
    added, and messaging never passes readiness in production and small.
    """
    run = runner or kubectl
    saved = []
    for item in config.get("env") or []:
        container = pod_container(item["workload"], item["namespace"], item["container"], run)
        entry = next((e for e in container.get("env") or [] if e["name"] == item["name"]), None)
        if entry is not None and "valueFrom" in entry:
            raise RuntimeError(
                f"{item['workload']} {item['container']} {item['name']} uses valueFrom; "
                "the sweep cannot put it back"
            )
        saved.append({
            "kind": "env",
            "workload": item["workload"],
            "namespace": item["namespace"],
            "container": item["container"],
            "name": item["name"],
            "value": None if entry is None else entry.get("value", ""),
        })
    for item in config.get("resources") or []:
        container = pod_container(item["workload"], item["namespace"], item["container"], run)
        resources = container.get("resources") or {}
        saved.append({
            "kind": "resources",
            "workload": item["workload"],
            "namespace": item["namespace"],
            "container": item["container"],
            "memory_request": (resources.get("requests") or {}).get("memory"),
            "memory_limit": (resources.get("limits") or {}).get("memory"),
        })
    return saved


def restore_commands(saved):
    """kubectl arguments that put the snapshot back. None removes the field."""
    commands = []
    for item in saved:
        target = [item["workload"], "-n", item["namespace"]]
        if item["kind"] == "env":
            if item["value"] is None:
                change = f"{item['name']}-"
            else:
                change = f"{item['name']}={item['value']}"
            commands.append(["set", "env", *target, "-c", item["container"], change])
            continue
        patch = {"spec": {"template": {"spec": {"containers": [{
            "name": item["container"],
            "resources": {
                "requests": {"memory": item["memory_request"]},
                "limits": {"memory": item["memory_limit"]},
            },
        }]}}}}
        commands.append(["patch", *target, "--type=strategic", "-p", json.dumps(patch)])
    return commands


def restore(config, saved, runner=None, wait=True):
    """Put the workloads back and wait, so the next config starts from the install."""
    run = runner or kubectl
    if not saved:
        return
    for command in restore_commands(saved):
        run(*command)
    if wait:
        rollout(rollout_items(config, False))


def rollout(items):
    started = time.monotonic()
    seen = False
    for item in items:
        kubectl("rollout", "restart", item["workload"], "-n", item["namespace"])
        try:
            kubectl("rollout", "status", item["workload"], "-n", item["namespace"], "--timeout=600s")
        except RuntimeError:
            diagnose(item["namespace"], item["workload"])
            raise
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
        return base64.b64decode(encoded).decode()
    # This branch still issues certificates with the upstream example password.
    return "atakatak"


def kubelet_samples(stop, sink, errors, pg_rss=None, containers=None, capacity_errors=None, raw_samples=None):
    while not stop.is_set():
        try:
            nodes = kubectl("get", "nodes", "-o", "name").stdout.split()
            rss = cpu = 0
            found = False
            pg_bytes = None
            for node in nodes:
                raw = kubectl("get", "--raw", f"/api/v1/nodes/{node.split('/', 1)[-1]}/proxy/stats/summary").stdout
                summary = json.loads(raw)
                if stop.is_set():
                    return
                if containers is not None:
                    capacity.observe(summary, containers, capacity_errors)
                if raw_samples is not None:
                    rows = []
                    for pod in summary.get('pods', []):
                        ref = pod.get('podRef', {})
                        if ref.get('namespace') not in capacity.NAMESPACES:
                            continue
                        for item in pod.get('containers', []):
                            memory, row_cpu = item.get('memory', {}), item.get('cpu', {})
                            rows.append({'namespace': ref.get('namespace'), 'pod_uid': ref.get('uid'),
                                         'container': item.get('name'), 'memory_time': memory.get('time'),
                                         'working_set_bytes': memory.get('workingSetBytes'),
                                         'cpu_time': row_cpu.get('time'), 'cpu_nanocores': row_cpu.get('usageNanoCores')})
                    if len(raw_samples) >= 400 or len(rows) > capacity.MAX_CONTAINERS:
                        capacity.note(capacity_errors, 'raw sample bound exceeded')
                    else:
                        raw_samples.append({'observed_unix': time.time(), 'containers': rows})
                for pod in summary.get("pods", []):
                    ref = pod.get("podRef", {})
                    if ref.get("namespace") not in ("takserver", "cloudtak"):
                        continue
                    for container in pod.get("containers", []):
                        memory = container.get("memory", {}).get("workingSetBytes")
                        usage = container.get("cpu", {}).get("usageNanoCores")
                        if memory is None or usage is None:
                            continue
                        found = True
                        rss += memory
                        cpu += usage
                        pod_name = str(ref.get("name", ""))
                        if (
                            ref.get("namespace") == "takserver"
                            and container.get("name") == "postgresql"
                            and pod_name.startswith("takserver-postgresql")
                        ):
                            pg_bytes = memory
            if found:
                sink.append({"rss": rss, "cpu": cpu})
            else:
                errors.append("kubelet summary had no TAK or CloudTAK stats")
            if pg_rss is not None and pg_bytes is not None:
                pg_rss.append(pg_bytes)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            errors.append(f"kubelet summary: {error}")
        stop.wait(5)


def capacity_inventory(errors):
    pods = []
    for namespace in capacity.NAMESPACES:
        try:
            raw = kubectl("get", "pods", "-n", namespace, "-o", "json").stdout
            pods.extend(json.loads(raw).get("items", []))
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            capacity.note(errors, f"{namespace} capacity inventory: {error}")
    return capacity.inventory(pods, quantity, errors)


def load_operation(operation, action, *args, **kwargs):
    """Keep credential-bearing process arguments and output out of failures."""
    try:
        return action(*args, **kwargs)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{operation}: process failed (exit {error.returncode})") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{operation}: process timed out") from None
    except OSError as error:
        raise RuntimeError(f"{operation}: operating system failure (errno {error.errno})") from None


def stop_load_forward(forward):
    if forward.poll() is None:
        forward.terminate()
        try:
            forward.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait(timeout=5)


def run_load(clients, duration, password, tester, study=False, boundary=None):
    if not tester.is_file():
        raise RuntimeError("load tester unavailable")
    cert_dir = Path(tempfile.mkdtemp(prefix="bench-certs-"))
    forward = None
    patched_dir = None
    proc = None
    output = None
    try:
        load_operation("certificate extraction", subprocess.run,
                       ["bash", str(ROOT / "tests" / "extract-certs.sh"), str(cert_dir)], check=True, cwd=ROOT)
        p12 = cert_dir / "admin.p12"
        load_operation(
            "certificate export", subprocess.run,
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
        forward = load_operation(
            "port forward launch", subprocess.Popen,
            [*kubectl_cmd(), "port-forward", "-n", "istio-passthrough-gateway",
             "svc/passthrough-ingressgateway", "18089:8089"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        time.sleep(2)
        # --send-metrics is omitted: upstream type=bool treats any present
        # string as true. --skip-mission-api avoids an unset mission config.
        # Keep the existing metrics interval and cumulative-bound mode.
        interval = max(1, duration // 3)
        patched_dir = Path(tempfile.mkdtemp(prefix="bench-tester-"))
        patched = patched_dir / "tak_tester.py"
        source = bind_tester(tester.read_text(encoding="utf-8"))
        patched.write_text(sustained.bind(source, ANCHOR) if study else source, encoding="utf-8")
        env = os.environ.copy()
        env["TAK_TESTER_DURATION"] = str(duration)
        env["BENCH_CUMULATIVE_STATS"] = "1"
        env["PYTHONPATH"] = str(tester.parent) + os.pathsep + env.get("PYTHONPATH", "")
        command = [
            sys.executable, "-u", str(patched),
            "--test-pytak", "--tls", "18089", "--host", "127.0.0.1",
            "--cert", str(p12), "--password", password,
            "--clients", str(clients), "--ping", "true",
            "--skip-mission-api",
            "--send-metrics-interval", str(interval),
        ]
        if study:
            command += ['--interval', '5', '--ping-interval', '5000']
            env['BENCH_WINDOW_READY'] = str(patched_dir / 'ready')
            env['BENCH_WINDOW_GO'] = str(patched_dir / 'go')
            env['BENCH_WINDOW_START'] = str(patched_dir / 'start')
            env['BENCH_WINDOW_END'] = str(patched_dir / 'end')
            output = tempfile.TemporaryFile(mode='w+')
        # Preserve the bounded tester and its process-group timeout escalation.
        proc = load_operation(
            "load tester launch", subprocess.Popen,
            command,
            cwd=tester.parent,
            env=env,
            start_new_session=True,
            stdout=output if study else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=(lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (16*1024*1024, 16*1024*1024))) if study else None,
        )
        if study:
            deadline = time.monotonic() + sustained.RAMP_DEADLINE + sustained.WARMUP + duration + 40
            ramp_until = time.monotonic() + sustained.RAMP_DEADLINE
            while not (patched_dir / 'ready').is_file():
                if time.monotonic() >= ramp_until or proc.poll() is not None:
                    raise ValueError('all 50 clients did not become connected before ramp deadline')
                time.sleep(0.2)
            warm_until = time.monotonic() + sustained.WARMUP
            while time.monotonic() < warm_until and proc.poll() is None:
                time.sleep(min(0.5, max(0, warm_until-time.monotonic())))
            if proc.poll() is not None:
                raise ValueError('load process exited during warmup')
            boundary('before')
            (patched_dir / 'go').touch(exist_ok=False)
            while not (patched_dir / 'start').is_file():
                if time.monotonic() >= deadline or proc.poll() is not None:
                    raise ValueError('measured start unavailable before deadline')
                time.sleep(0.2)
            boundary('started')
            while not (patched_dir / 'end').is_file():
                if time.monotonic() >= deadline or proc.poll() is not None:
                    raise ValueError('measured boundary unavailable before deadline')
                time.sleep(0.2)
            boundary('after')
            load_operation("measured load cleanup", proc.wait, timeout=20)
            if proc.returncode:
                raise ValueError('load process failed after measured window')
            output.seek(0)
            text = output.read(16*1024*1024)
        else:
            text = load_operation("load tester wait", reap, proc, duration + 20)
        try:
            return sustained.parse_window(text) if study else parse(text)
        except sustained.WindowInvalid:
            raise
        except ValueError:
            raise ValueError("load metrics invalid or missing") from None
    finally:
        if study and proc is not None:
            kill_group(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if output is not None:
            output.close()
        try:
            if forward is not None:
                load_operation("port forward cleanup", stop_load_forward, forward)
        finally:
            if patched_dir is not None:
                shutil.rmtree(patched_dir, ignore_errors=True)
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
        "start_phases": {"takserver-messaging": None, "takserver-api": None},
        "startup": {"max_generation": None, "max_restart_count": None},
        "load": {
            "clients": clients,
            "duration_s": duration,
            "counter_source": "parent-cumulative-ramp-inclusive",
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
        "postgres": None,
        "capacity": None,
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


def one(config, clients, out_dir, tester, cold, study=False):
    duration = int(config["duration_s"])
    record = blank(arch_name(), config["name"], clients, duration)
    if study:
        record['study'] = config['study']
    try:
        postgres_changed = apply_postgres(config)
        apply_config(config)
        if config.get("restart") or postgres_changed:
            record["time_to_ready"]["warm_s"] = rollout(rollout_items(config, postgres_changed))
            record["time_to_ready"]["cold_s"] = cold
        else:
            record["time_to_ready"]["cold_s"] = cold
        fp, fp_errors = footprint()
        record["footprint"] = fp
        record["errors"].extend(fp_errors)
        phases, phase_errors = start_phases()
        record["start_phases"] = phases
        record["errors"].extend(phase_errors)
        shape, shape_errors = startup_shape()
        record["startup"] = shape
        record["errors"].extend(shape_errors)
        record["package_bytes"] = package_bytes()
        if record["package_bytes"] is None:
            record["errors"].append("no zarf-package-takserver tarball to stat")
        try:
            record["images"] = config.get("cached_images") or image_bytes()
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            record["errors"].append(f"image bytes: {error}")
        samples = []
        pg_rss = []
        sample_errors = []
        capacity_errors = []
        containers = {}
        capacity_before = capacity_inventory(capacity_errors)
        stop = threading.Event()
        thread = threading.Thread(
            target=kubelet_samples,
            args=(stop, samples, sample_errors, pg_rss, containers, capacity_errors), daemon=True,
        )
        window = {}
        raw_samples = []
        if study:
            thread = threading.Thread(target=kubelet_samples, args=(stop, samples, sample_errors, pg_rss, containers, capacity_errors, raw_samples), daemon=True)
        def boundary(phase):
            # Keep raw DB snapshots and their bracket timestamps; no reset can
            # erase warmup activity or checkpoint evidence.
            if phase == 'before':
                window['before_unix'] = time.time()
                window['cgroup_before'] = postgres_cgroup()
                window['database_version'] = postgres_version()
                window['database_before_started_unix'] = time.time()
                window['postgres_before'] = read_postgres([])
                window['database_before_finished_unix'] = time.time()
                window['capacity_before'] = capacity_inventory(capacity_errors)
                samples.clear()
                pg_rss.clear()
                containers.clear()
                window['before_finished_unix'] = time.time()
            elif phase == 'started':
                thread.start()
                window['memory_started_unix'] = time.time()
            else:
                stop.set()
                window['after_unix'] = time.time()
                window['database_after_started_unix'] = time.time()
                window['postgres_after'] = read_postgres(pg_rss)
                window['database_after_finished_unix'] = time.time()
                window['cgroup_after'] = postgres_cgroup()
                stop.set()
                thread.join(timeout=10)
                window['capacity_after'] = capacity_inventory(capacity_errors)
                window['after_finished_unix'] = time.time()
        if not study:
            thread.start()
        try:
            try:
                if not study:
                    reset_postgres_counters()
            except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
                record["errors"].append(f"postgres counters: {error}")
            password = keystore_password()
            parsed = run_load(clients, duration, password, tester, study=True, boundary=boundary) if study else run_load(clients, duration, password, tester)
            record["load"].update(parsed)
        except (RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as error:
            if isinstance(error, sustained.WindowInvalid):
                record["load"]["window"] = error.window
                record["study"]["outcome"] = error.category
            record["errors"].append(f"load: {error}")
        finally:
            stop.set()
            if thread.ident is not None:
                thread.join(timeout=10)
        record["errors"].extend(sample_errors)
        if thread.is_alive():
            capacity_errors = list(capacity_errors)
            capacity.note(capacity_errors, "sampler did not stop; per-container samples were omitted")
            containers = {}
        capacity_after = capacity_inventory(capacity_errors)
        if study:
            capacity_before = window.get('capacity_before', {})
            capacity_after = window.get('capacity_after', {})
        record["capacity"] = capacity.assemble(capacity_before, capacity_after, containers, capacity_errors)
        record["errors"].extend(f"capacity: {error}" for error in record["capacity"]["errors"])
        try:
            if study:
                record['postgres'] = sustained.postgres_delta(window['postgres_before'], window['postgres_after'])
                record['study']['memory_samples'] = raw_samples
                record['study']['database_version'] = window['database_version']
                record['study']['cgroup_before'] = window['cgroup_before']
                record['study']['cgroup_after'] = window['cgroup_after']
                if window['cgroup_before'] != window['cgroup_after']:
                    raise ValueError('PostgreSQL cgroup limits changed')
                record['study']['database_boundary'] = {k: v for k,v in window.items() if k.endswith('_unix')}
                end = (record['load'].get('window') or {}).get('end_unix')
                start = (record['load'].get('window') or {}).get('start_unix')
                if (end is None or start is None or not 0 <= start-window['database_before_started_unix'] <= 5
                        or not 0 <= window['database_after_finished_unix']-end <= 5):
                    raise ValueError('PostgreSQL boundary outside five-second bracket tolerance')
            else:
                record["postgres"] = read_postgres(pg_rss)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as error:
            record["errors"].append(f"postgres: {error}")
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
    try:
        study = sustained.enabled()
        configs = selected_configs(sorted(config_dir.glob("*.yaml")))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if not configs:
        print("no bench configs", file=sys.stderr)
        return 2
    if not shutil.which("kubectl") and not shutil.which("uds"):
        print("kubectl is not available, so no benchmark record was written", file=sys.stderr)
        return 2
    if study:
        spec = importlib.util.spec_from_file_location('ephemeral', ROOT / 'tests/ephemeral-cluster.py')
        ephemeral = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ephemeral)
        def guarded_command(argv):
            return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15).stdout
        proof = ephemeral.verify('k3d-uds', guarded_command)
    cold, cold_errors = ready_age()
    failed = False
    cached_images = None
    for original in configs:
        if original.get("skip"):
            reason = original.get("reason") or "skipped"
            print(f"skip {original['name']}: {reason}")
            continue
        counts = [50] * sustained.REPEATS if study else selected_clients(original)
        if study:
            original = {**original, 'duration_s': sustained.DURATION}
            provenance = sustained.provenance(original, git_sha(), tester)
        try:
            saved = snapshot(original)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            failed = True
            print(f"{original['name']}: snapshot: {error}", file=sys.stderr)
            continue
        for index, clients in enumerate(counts):
            # The first client count keeps the config name. Further counts
            # get a suffix so they do not overwrite that file.
            name = original["name"] if index == 0 else f"{original['name']}-c{clients}"
            if study:
                if ephemeral.verify('k3d-uds', guarded_command) != proof:
                    raise ValueError('owned ephemeral cluster proof changed')
                name = f"baseline-r{index+1}"
                config = {**original, 'name': name, 'cached_images': cached_images, 'study': {**provenance, 'repeat': index+1}}
                config['study']['runner'] = {'machine': platform.machine(), 'kernel': platform.release(), 'logical_cpus': os.cpu_count()}
                record = one(config, clients, out_dir, tester, cold, study=True)
                cached_images = record.get('images')
            else:
                record = one({**original, "name": name}, clients, out_dir, tester, cold)
            if cold_errors and not original.get("restart"):
                record["errors"].extend(cold_errors)
                write_record(record, out_dir)
            if record["errors"]:
                failed = True
                print(f"{name}: " + "; ".join(record["errors"]), file=sys.stderr)
                if study:
                    return 1  # Do not spend two more trials after an invalid baseline.
        try:
            restore(original, saved)
        except (RuntimeError, subprocess.CalledProcessError) as error:
            # Every later config would run on top of this one.
            print(f"{original['name']}: restore: {error}; stopping the sweep", file=sys.stderr)
            return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
