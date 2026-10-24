#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Readiness and kubectl top checks for the full-core job.

The memory requests and limits compared here are the same literals the
startup task in tasks/test.yaml asserts. This file does not contain cluster
measurements. Callers pass kubectl JSON and kubectl top text in.
"""

import argparse
import json
import re
import sys

# tasks/test.yaml startup task. A change there has to change this tuple too.
ASSERTED = (
    ("statefulset", "takserver-ignite", "limits", "memory", "1536Mi"),
    ("statefulset", "takserver-ignite", "requests", "memory", "512Mi"),
    ("deployment", "takserver-plugins", "limits", "memory", "384Mi"),
    ("deployment", "takserver-config", "requests", "memory", "512Mi"),
)

UNITS = {
    "Ki": 2**10,
    "Mi": 2**20,
    "Gi": 2**30,
    "Ti": 2**40,
    "k": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
}

TOP_LINE = re.compile(
    r"^(?P<name>\S+)\s+(?P<cpu>\d+(?:\.\d+)?m?)\s+(?P<memory>\d+(?:\.\d+)?(?:Ki|Mi|Gi|Ti|k|M|G|T)?)$"
)


def parse_bytes(value):
    if value is None or value == "":
        return None
    for suffix, factor in UNITS.items():
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * factor)
    return int(float(value))


def parse_top(text):
    rows = []
    errors = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().startswith("name"):
            continue
        match = TOP_LINE.match(line)
        if not match:
            errors.append(f"kubectl top line is not numeric: {line}")
            continue
        rows.append(
            {
                "name": match.group("name"),
                "cpu": match.group("cpu"),
                "memory": match.group("memory"),
                "memory_bytes": parse_bytes(match.group("memory")),
            }
        )
    return rows, errors


def ready_pods(pod_list):
    """Return (ready_count, problems). Succeeded pods are finished Jobs."""
    problems = []
    ready = 0
    for pod in pod_list.get("items", []):
        name = pod.get("metadata", {}).get("name", "")
        phase = pod.get("status", {}).get("phase")
        if phase == "Succeeded":
            continue
        if phase != "Running":
            problems.append(f"{name} phase {phase}")
            continue
        statuses = pod.get("status", {}).get("containerStatuses") or []
        if not statuses or not all(status.get("ready") for status in statuses):
            problems.append(f"{name} is not Ready")
            continue
        ready += 1
    if ready == 0:
        problems.append("no Ready pods")
    return ready, problems


def limit_bytes(pod):
    total = 0
    for container in pod.get("spec", {}).get("containers", []):
        memory = container.get("resources", {}).get("limits", {}).get("memory")
        parsed = parse_bytes(memory) if memory else None
        if parsed is None:
            return None
        total += parsed
    return total


def workload_resources(workload):
    containers = (
        workload.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    if not containers:
        return {}
    return containers[0].get("resources", {})


def check_asserted(workloads):
    """workloads maps (kind, name) to a Deployment or StatefulSet object."""
    lines = []
    errors = []
    for kind, name, side, resource, want in ASSERTED:
        body = workloads.get((kind, name))
        if body is None:
            errors.append(f"missing {kind}/{name}")
            continue
        got = workload_resources(body).get(side, {}).get(resource)
        lines.append(f"{kind}/{name} {side}.{resource}: live {got}, asserted {want}")
        if got != want:
            errors.append(f"{kind}/{name} {side}.{resource} is {got}, asserted {want}")
    return lines, errors


def check_top(top_text, pods_by_namespace):
    rows, errors = parse_top(top_text)
    lines = []
    by_name = {row["name"]: row for row in rows}
    for namespace, pod_list in pods_by_namespace.items():
        names = [
            pod.get("metadata", {}).get("name", "")
            for pod in pod_list.get("items", [])
            if pod.get("status", {}).get("phase") == "Running"
        ]
        if not names:
            errors.append(f"{namespace}: no Running pods to measure")
            continue
        seen = 0
        for name in names:
            row = by_name.get(name)
            if row is None:
                errors.append(f"{namespace}/{name} missing from kubectl top")
                continue
            seen += 1
            pod = next(
                pod
                for pod in pod_list["items"]
                if pod.get("metadata", {}).get("name") == name
            )
            ceiling = limit_bytes(pod)
            used = row["memory_bytes"]
            ceiling_text = "no memory limit" if ceiling is None else str(ceiling)
            lines.append(
                f"{namespace}/{name} cpu {row['cpu']} memory {row['memory']} limit-bytes {ceiling_text}"
            )
            if ceiling is not None and used > ceiling:
                errors.append(
                    f"{namespace}/{name} memory {row['memory']} is over the sum of container limits"
                )
        if seen == 0:
            errors.append(f"{namespace}: kubectl top returned no rows")
    return lines, errors


def main(argv):
    parser = argparse.ArgumentParser(description="Full-core readiness and top checks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ready = sub.add_parser("ready")
    ready.add_argument("namespace")

    top = sub.add_parser("top")
    top.add_argument("--top-file", required=True)
    top.add_argument("--pods", action="append", required=True, metavar="NS=PATH")
    top.add_argument("--workload", action="append", default=[], metavar="KIND/NAME=PATH")

    args = parser.parse_args(argv)
    if args.cmd == "ready":
        pod_list = json.load(sys.stdin)
        count, problems = ready_pods(pod_list)
        if problems:
            print(f"{args.namespace}: " + "; ".join(problems), file=sys.stderr)
            return 1
        print(f"{args.namespace}: {count} Ready pods")
        return 0

    pods_by_namespace = {}
    for item in args.pods:
        namespace, path = item.split("=", 1)
        with open(path, encoding="utf-8") as handle:
            pods_by_namespace[namespace] = json.load(handle)
    workloads = {}
    for item in args.workload:
        ident, path = item.split("=", 1)
        kind, name = ident.split("/", 1)
        with open(path, encoding="utf-8") as handle:
            workloads[(kind, name)] = json.load(handle)
    with open(args.top_file, encoding="utf-8") as handle:
        top_text = handle.read()
    lines, errors = check_asserted(workloads)
    top_lines, top_errors = check_top(top_text, pods_by_namespace)
    lines.extend(top_lines)
    errors.extend(top_errors)
    print("\n".join(lines))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
