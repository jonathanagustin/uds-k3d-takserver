#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pareto report over benchmark JSON. Records with a null axis are skipped."""

import json
import sys
from pathlib import Path


VIEWS = (
    ("footprint_bytes", "throughput", False, True, "footprint vs throughput"),
    ("footprint_bytes", "latency_ms", False, False, "footprint vs mean latency"),
    ("footprint_bytes", "ready_s", False, False, "footprint vs time-to-ready"),
)


def point(record):
    load = record.get("load") or {}
    kubelet = record.get("kubelet") or {}
    ready = record.get("time_to_ready") or {}
    duration = load.get("duration_s")
    received = load.get("messages_received")
    throughput = None
    if duration and received is not None:
        throughput = received / duration
    ready_s = ready.get("warm_s")
    if ready_s is None:
        ready_s = ready.get("cold_s")
    return {
        "config": record.get("config"),
        "arch": record.get("arch"),
        "footprint_bytes": kubelet.get("steady_rss_bytes"),
        "throughput": throughput,
        "latency_ms": load.get("ping_pong_ms_mean"),
        "ready_s": ready_s,
        "errors": record.get("errors") or [],
    }


def better(left, right, higher):
    if higher:
        return left > right
    return left < right


def dominates(left, right, x_key, y_key, x_higher, y_higher):
    x_better = better(left[x_key], right[x_key], x_higher) or left[x_key] == right[x_key]
    y_better = better(left[y_key], right[y_key], y_higher) or left[y_key] == right[y_key]
    strict = better(left[x_key], right[x_key], x_higher) or better(left[y_key], right[y_key], y_higher)
    return x_better and y_better and strict


def front(points, x_key, y_key, x_higher, y_higher):
    usable = [p for p in points if p[x_key] is not None and p[y_key] is not None]
    dominated = []
    kept = []
    for candidate in usable:
        beaten = False
        for other in usable:
            if other is candidate:
                continue
            if dominates(other, candidate, x_key, y_key, x_higher, y_higher):
                beaten = True
                break
        if beaten:
            dominated.append(candidate)
        else:
            kept.append(candidate)
    return kept, dominated


def load_records(paths):
    records = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
        if body.get("schema") != 1:
            raise SystemExit(f"{path} is not schema 1")
        records.append(body)
    return records


def markdown(records):
    lines = ["# Benchmark front", ""]
    by_arch = {}
    for record in records:
        by_arch.setdefault(record.get("arch"), []).append(point(record))
    if not by_arch:
        lines.append("No records.")
        lines.extend(postgres_lines(records))
        return "\n".join(lines) + "\n"
    for arch, points in sorted(by_arch.items()):
        lines.append(f"## {arch}")
        lines.append("")
        for x_key, y_key, x_higher, y_higher, title in VIEWS:
            kept, dominated = front(points, x_key, y_key, x_higher, y_higher)
            lines.append(f"### {title}")
            lines.append("")
            if not kept and not dominated:
                lines.append("No config had both axes.")
                lines.append("")
                continue
            lines.append("Front: " + ", ".join(sorted(p["config"] for p in kept)))
            if dominated:
                lines.append("Dominated: " + ", ".join(sorted(p["config"] for p in dominated)))
            else:
                lines.append("Dominated: none")
            lines.append("")
    lines.extend(postgres_lines(records))
    return "\n".join(lines)


def postgres_lines(records):
    """Hit ratio, temp files, checkpoints, and RSS beside TAK throughput."""
    lines = ["## Postgres", ""]
    found = False
    for record in records:
        stats = record.get("postgres")
        if not stats:
            continue
        found = True
        load = record.get("load") or {}
        duration = load.get("duration_s")
        received = load.get("messages_received")
        throughput = None
        if duration and received is not None:
            throughput = round(received / duration, 3)
        settings = stats.get("settings") or {}
        lines.append(
            "- {arch} {config}: hit_ratio {hit}, temp_bytes {temp}, "
            "checkpoints_req {checks}, rss {rss}, throughput {rate}, "
            "shared_buffers {buffers}".format(
                arch=record.get("arch"),
                config=record.get("config"),
                hit=stats.get("hit_ratio"),
                temp=stats.get("temp_bytes"),
                checks=stats.get("checkpoints_req"),
                rss=stats.get("steady_rss_bytes"),
                rate=throughput,
                buffers=settings.get("shared_buffers"),
            )
        )
    if not found:
        lines.append("No Postgres stats.")
    lines.append("")
    return lines


def _scale(values, low, high):
    span = max(values) - min(values)
    if span == 0:
        return {value: (low + high) / 2 for value in values}

    def convert(value):
        return low + (value - min(values)) * (high - low) / span

    return {value: convert(value) for value in values}


def svg(records):
    width, height, panel = 680, 220, 200
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height * 3}">',
    ]
    by_arch = {}
    for record in records:
        by_arch.setdefault(record.get("arch"), []).append(point(record))
    colors = {"amd64": "#1f4e79", "arm64": "#9a3412"}
    offset = 0
    for x_key, y_key, x_higher, y_higher, title in VIEWS:
        parts.append(f'<text x="16" y="{offset + 18}" font-family="sans-serif" font-size="14">{title}</text>')
        for arch, points in sorted(by_arch.items()):
            kept, dominated = front(points, x_key, y_key, x_higher, y_higher)
            usable = kept + dominated
            if not usable:
                continue
            xs = _scale([p[x_key] for p in usable], 40, width - 20)
            ys = _scale([p[y_key] for p in usable], offset + panel - 16, offset + 36)
            front_ids = {id(p) for p in kept}
            for item in usable:
                fill = colors.get(arch, "#333")
                if id(item) in front_ids:
                    attrs = f'fill="{fill}"'
                else:
                    attrs = f'fill="none" stroke="{fill}" stroke-width="2"'
                parts.append(
                    f'<circle cx="{xs[item[x_key]]:.1f}" cy="{ys[item[y_key]]:.1f}" r="5" {attrs}>'
                    f"<title>{arch} {item['config']}</title></circle>"
                )
        offset += height
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv):
    if len(argv) < 3:
        print("usage: report.py <out-dir> <record.json>...", file=sys.stderr)
        return 2
    out = Path(argv[0])
    records = load_records(argv[1:])
    if not records:
        print("no benchmark records", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    text = markdown(records)
    (out / "front.md").write_text(text, encoding="utf-8")
    (out / "front.svg").write_text(svg(records), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
