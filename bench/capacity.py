# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded per-container observations, not a continuous memory maximum."""

import math

NAMESPACES = ("takserver", "cloudtak")
MAX_CONTAINERS = 256


def note(errors, message):
    if message not in errors:
        errors.append(message)


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def inventory(pods, quantity, errors):
    found = {}
    for pod in pods:
        metadata = pod.get("metadata") or {}
        namespace, uid = metadata.get("namespace"), metadata.get("uid")
        if namespace not in NAMESPACES or (pod.get("status") or {}).get("phase") != "Running":
            continue
        if not uid:
            note(errors, f"{namespace}/{metadata.get('name')} has no pod UID")
            continue
        statuses = {s.get("name"): s for s in (pod.get("status") or {}).get("containerStatuses") or []}
        for container in (pod.get("spec") or {}).get("containers") or []:
            name = container.get("name")
            key = (namespace, uid, name)
            if len(found) >= MAX_CONTAINERS:
                note(errors, f"container inventory exceeded {MAX_CONTAINERS}; evidence truncated")
                return found
            status = statuses.get(name) or {}
            if number(status.get("restartCount")) is None:
                note(errors, f"{namespace}/{metadata.get('name')}/{name} has no readable restart count")
            resources = container.get("resources") or {}
            limit = (resources.get("limits") or {}).get("memory")
            try:
                limit_bytes = quantity(limit) if limit else None
            except (ValueError, TypeError):
                limit_bytes = None
            if limit_bytes is None:
                note(errors, f"{namespace}/{metadata.get('name')}/{name} has no readable memory limit")
            found[key] = {
                "namespace": namespace, "pod": metadata.get("name"), "pod_uid": uid, "container": name,
                "memory_limit_bytes": limit_bytes,
                "restart_count": status.get("restartCount"),
                "ready": status.get("ready"),
                "termination_reason": ((status.get("state") or {}).get("terminated") or {}).get("reason"),
                "last_termination_reason": ((status.get("lastState") or {}).get("terminated") or {}).get("reason"),
            }
    return found


def observe(summary, samples, errors):
    for pod in summary.get("pods") or []:
        ref = pod.get("podRef") or {}
        namespace, uid = ref.get("namespace"), ref.get("uid")
        if namespace not in NAMESPACES:
            continue
        if not uid:
            note(errors, f"{namespace}/{ref.get('name')} summary has no pod UID")
            continue
        for container in pod.get("containers") or []:
            name = container.get("name")
            key = (namespace, uid, name)
            if key not in samples:
                if len(samples) >= MAX_CONTAINERS:
                    note(errors, f"container samples exceeded {MAX_CONTAINERS}; evidence truncated")
                    continue
                samples[key] = {
                    "namespace": namespace, "pod": ref.get("name"), "pod_uid": uid, "container": name,
                    "memory_sample_count": 0, "cpu_sample_count": 0,
                    "peak_working_set_bytes": None, "last_working_set_bytes": None,
                    "peak_cpu_nanocores": None, "last_cpu_nanocores": None,
                    "first_memory_time": None, "last_memory_time": None,
                }
            row = samples[key]
            memory = container.get("memory") or {}
            for value, prefix, last_key, peak_key in (
                (memory.get("workingSetBytes"), "memory", "last_working_set_bytes", "peak_working_set_bytes"),
                ((container.get("cpu") or {}).get("usageNanoCores"), "cpu", "last_cpu_nanocores", "peak_cpu_nanocores"),
            ):
                value = number(value)
                if value is None:
                    continue
                row[f"{prefix}_sample_count"] += 1
                row[last_key] = value
                row[peak_key] = value if row[peak_key] is None else max(row[peak_key], value)
                if prefix == "memory":
                    if row["first_memory_time"] is None:
                        row["first_memory_time"] = memory.get("time")
                    row["last_memory_time"] = memory.get("time")


def assemble(before, after, samples, errors):
    rows = []
    for key in sorted(set(before) | set(after) | set(samples)):
        old, new, sampled = before.get(key), after.get(key), samples.get(key)
        identity = old or new or sampled
        label = f"{identity['namespace']}/{identity['pod']}/{identity['container']}"
        if old is None or new is None:
            note(errors, f"{label} was not present in both boundary inventories; inspect pod replacement")
        if old and new:
            if old["restart_count"] != new["restart_count"]:
                note(errors, f"{label} restart count changed during the sampling window")
            if old["memory_limit_bytes"] != new["memory_limit_bytes"]:
                note(errors, f"{label} memory limit changed during the sampling window")
        for boundary in (old, new):
            if boundary and boundary["ready"] is not True:
                note(errors, f"{label} was not Ready in a boundary inventory")
            if boundary and "OOMKilled" in (boundary["termination_reason"], boundary["last_termination_reason"]):
                note(errors, f"{label} has OOMKilled termination evidence")
        if sampled is None or not sampled["memory_sample_count"]:
            note(errors, f"{label} has no memory samples")
        if sampled is None or not sampled["cpu_sample_count"]:
            note(errors, f"{label} has no CPU samples")
        if sampled and sampled["memory_sample_count"] and sampled["last_memory_time"] is None:
            note(errors, f"{label} memory samples have no source timestamp")
        rows.append({
            "namespace": identity["namespace"], "pod": identity["pod"],
            "pod_uid": identity["pod_uid"], "container": identity["container"],
            "before": old, "after": new, "samples": sampled,
        })
    return {"sample_interval_s": 5, "containers": rows, "errors": list(errors)}
