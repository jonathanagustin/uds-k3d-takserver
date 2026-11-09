#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Pareto report over benchmark JSON. Records with a null axis are skipped."""

import json
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape


VIEWS = (
    ("footprint_bytes", "throughput", False, True, "footprint vs throughput"),
    ("footprint_bytes", "latency_ms", False, False, "footprint vs mean latency"),
    ("footprint_bytes", "warm_ready_s", False, False, "footprint vs warm rollout time"),
)


def nonnegative(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def cohorts(records):
    """Compare only matched revision, client count and measured duration.

    Incomplete metadata isolates a record; unknown is not a shared workload.
    Input JSON stays untouched so historical defects remain inspectable.
    """
    groups = {}
    for index, record in enumerate(records):
        load = record.get("load") or {}
        revision = record.get("git_sha")
        clients = nonnegative(load.get("clients"))
        duration = nonnegative(load.get("duration_s"))
        if revision and clients and duration:
            key = (revision, clients, duration)
            label = f"clients={clients}, duration={duration} s, revision={revision}"
        else:
            key = ("incomplete", index)
            label = f"record {index + 1}: incomplete comparison metadata (not ranked against other records)"
        groups.setdefault(key, (label, []))[1].append(record)
    return list(groups.values())


def point(record):
    load = record.get("load") or {}
    kubelet = record.get("kubelet") or {}
    ready = record.get("time_to_ready") or {}
    duration = nonnegative(load.get("duration_s"))
    received = nonnegative(load.get("messages_received"))
    throughput = None
    if duration and received is not None:
        throughput = received / duration
    ready_s = ready.get("warm_s")
    if ready_s is None:
        ready_s = ready.get("cold_s")
    return {
        "config": record.get("config"),
        "arch": record.get("arch"),
        "footprint_bytes": nonnegative(kubelet.get("steady_rss_bytes")),
        "throughput": throughput,
        "latency_ms": nonnegative(load.get("ping_pong_ms_mean")),
        "ready_s": nonnegative(ready_s),
        "cold_ready_s": nonnegative(ready.get("cold_s")),
        "warm_ready_s": nonnegative(ready.get("warm_s")),
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
    if not records:
        return "# Benchmark front\n\nNo records.\n\nNo Postgres stats.\n"
    lines.extend([
        "Each workload cohort has one scale per view across architectures. Dominance is per architecture within a matched revision, client count and duration.",
        "Cold install age is a shared reference in the evidence table, not a swept-config ranking. The readiness plot uses warm rollout duration only. Missing or invalid axes are not plotted. These are individual observations, not confidence intervals.",
        "",
    ])
    for label, matched in cohorts(records):
        lines.extend([f"## Cohort: {label}", ""])
        by_arch = {}
        for record in matched:
            by_arch.setdefault(record.get("arch"), []).append(point(record))
        for arch, points in sorted(by_arch.items()):
            lines.extend([f"### {arch}", ""])
            for x_key, y_key, x_higher, y_higher, title in VIEWS:
                kept, dominated = front(points, x_key, y_key, x_higher, y_higher)
                lines.extend([f"#### {title}", ""])
                if not kept and not dominated:
                    lines.extend(["No config had both axes.", ""])
                    continue
                lines.append("Front: " + ", ".join(sorted(p["config"] for p in kept)))
                lines.append("Dominated: " + (", ".join(sorted(p["config"] for p in dominated)) or "none"))
                lines.append("")
        lines.extend(measurement_lines(matched))
        lines.extend(startup_lines(matched))
        lines.extend(postgres_lines(matched))
        lines.extend(["### Record caveats", ""])
        caveats = [f"- {cell(r.get('arch'))} {cell(r.get('config'))}: {cell(error)}"
                   for r in matched for error in r.get("errors") or []]
        lines.extend(caveats or ["No collection errors were recorded. This does not establish comparability beyond the stored metadata."])
        lines.append("")
    return "\n".join(lines)


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def measured(value, divisor=1):
    if value is None:
        return "not measured"
    valid = nonnegative(value)
    if valid is None:
        return f"invalid ({cell(value)})"
    return f"{valid / divisor:.3f}"


def measurement_lines(records):
    lines = ["### Observed load and footprint", "",
             "| Architecture | Config | Steady working set (MiB) | Peak working set (MiB) | Steady CPU (m) | Received messages/s | Mean ping-pong (ms) | Cold install reference (s) | Warm rollout (s) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for record in records:
        sample = point(record)
        kubelet = record.get("kubelet") or {}
        ready = record.get("time_to_ready") or {}
        values = [cell(record.get("arch")), cell(record.get("config")),
                  measured(kubelet.get("steady_rss_bytes"), 2**20), measured(kubelet.get("peak_rss_bytes"), 2**20),
                  measured(kubelet.get("steady_cpu_nanocores"), 10**6), measured(sample["throughput"]),
                  measured(sample["latency_ms"]), measured(ready.get("cold_s")), measured(ready.get("warm_s"))]
        lines.append("| " + " | ".join(values) + " |")
    return [*lines, ""]


def startup_lines(records):
    lines = ["### Observed pod startup phases", "",
             "These are the pods observed at each config's collection time. A database-only rollout can reuse an earlier TAK pod; these rows are not proof that each config independently measured both a cold and a warm TAK start. Container start includes entrypoint work and does not measure JVM start or class loading. Legacy jvm_to_log_s values also used container timestamps. Negative timings are invalid observations, not durations.", "",
             "| Architecture | Config | App | Image pull (s) | Init containers (s) | Container start to first startup log (s) | Startup log to Ready (s) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for record in records:
        phases = record.get("start_phases") or {}
        for app in ("takserver-messaging", "takserver-api"):
            phase = phases.get(app) or {}
            inits = phase.get("inits")
            init_text = "; ".join(f"{cell(item.get('name'))}: {measured(item.get('seconds'))}" for item in inits) if inits else "not measured"
            values = [cell(record.get("arch")), cell(record.get("config")), app,
                      measured(phase.get("image_pull_s")), init_text,
                      measured(phase.get("container_to_log_s", phase.get("jvm_to_log_s"))), measured(phase.get("log_to_ready_s"))]
            lines.append("| " + " | ".join(values) + " |")
    return [*lines, ""]


def postgres_lines(records):
    """Hit ratio, temp files, checkpoints, and RSS beside TAK throughput."""
    lines = ["### Postgres", ""]
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
    width, height = 740, 280
    groups = cohorts(records)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height * len(VIEWS) * max(1, len(groups))}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    colors = {"amd64": "#1f4e79", "arm64": "#9a3412"}
    offset = 0
    for label, matched in groups:
        by_arch = {}
        for record in matched:
            by_arch.setdefault(record.get("arch"), []).append(point(record))
        for x_key, y_key, x_higher, y_higher, title in VIEWS:
            parts.append(f'<text x="16" y="{offset + 18}" font-family="sans-serif" font-size="14">{escape(title)}</text>')
            parts.append(f'<text x="16" y="{offset + 35}" font-family="sans-serif" font-size="10">{escape(label)}</text>')
            plotted = []
            for arch, points in sorted(by_arch.items()):
                kept, dominated = front(points, x_key, y_key, x_higher, y_higher)
                plotted.extend((arch, item, True) for item in kept)
                plotted.extend((arch, item, False) for item in dominated)
            if plotted:
                x_values = [row[1][x_key] for row in plotted]
                y_values = [row[1][y_key] for row in plotted]
                xs = _scale(x_values, 80, width - 25)
                ys = _scale(y_values, offset + 195, offset + 65)
                unit = "messages/s" if y_key == "throughput" else "ms" if y_key == "latency_ms" else "s"
                parts.append(f'<path d="M80 {offset + 65}V{offset + 195}H{width - 25}" fill="none" stroke="#666"/>')
                for value in sorted(set((min(x_values), max(x_values)))):
                    parts.append(f'<text x="{xs[value]:.1f}" y="{offset + 212}" text-anchor="middle" font-family="sans-serif" font-size="10">{value / 2**20:.1f}</text>')
                for value in sorted(set((min(y_values), max(y_values)))):
                    parts.append(f'<text x="74" y="{ys[value] + 3:.1f}" text-anchor="end" font-family="sans-serif" font-size="10">{value:.3f}</text>')
                parts.append(f'<text x="80" y="{offset + 55}" font-family="sans-serif" font-size="10">{unit}</text>')
                parts.append(f'<text x="{width / 2}" y="{offset + 232}" text-anchor="middle" font-family="sans-serif" font-size="11">Steady working set (MiB)</text>')
                for arch, item, on_front in plotted:
                    fill = colors.get(arch, "#333")
                    attrs = f'fill="{fill}"' if on_front else f'fill="none" stroke="{fill}" stroke-width="2"'
                    parts.append(
                        f'<circle cx="{xs[item[x_key]]:.1f}" cy="{ys[item[y_key]]:.1f}" r="5" {attrs}>'
                        f"<title>{escape(str(arch))} {escape(str(item['config']))}</title></circle>"
                    )
            else:
                parts.append(f'<text x="80" y="{offset + 100}" font-family="sans-serif" font-size="12">No records have both valid axes.</text>')
            parts.append(f'<text x="16" y="{offset + 263}" fill="#1f4e79" font-family="sans-serif" font-size="11">amd64</text>')
            parts.append(f'<text x="80" y="{offset + 263}" fill="#9a3412" font-family="sans-serif" font-size="11">arm64</text>')
            parts.append(f'<text x="150" y="{offset + 263}" font-family="sans-serif" font-size="11">Filled: cohort front; open: dominated in that architecture</text>')
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
