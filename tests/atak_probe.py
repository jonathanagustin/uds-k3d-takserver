# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pick the ATAK viewer series out of a Prometheus probe_success response."""

import json
import sys


def _rows(payload):
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data", {}).get("result", []) or []
    found = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric = row.get("metric") or {}
        instance = str(metric.get("instance", ""))
        value = ""
        raw = row.get("value")
        if isinstance(raw, list) and len(raw) > 1:
            value = str(raw[1])
        found.append((value, instance))
    return found


def viewer_series(payload):
    """Return (value, instance) for series whose instance is the phone page."""
    return [
        (value, instance)
        for value, instance in _rows(payload)
        if "atak." in instance and "phone.html" in instance
    ]


def main(argv):
    args = argv[1:]
    show_all = False
    if args and args[0] == "--all":
        show_all = True
        args = args[1:]
    if len(args) != 1:
        print("usage: atak_probe.py [--all] <prometheus-json>", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        payload = json.load(handle)
    found = _rows(payload) if show_all else viewer_series(payload)
    if not found:
        return 2
    for value, instance in found:
        print(f"{value} {instance}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
