#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Read the counters tak_tester.py prints when CloudWatch is off.

The 5.7-RELEASE-14 printer sleeps, prints the shared array, then zeroes it.
Each line is one interval, so the record adds every line. A log with no such
line is an error, not a zero.
"""

import ast
import json
import re
import sys

LINE = re.compile(
    r"Info that would be sent to CloudWatch if it was enabled, uid: (?P<uid>\S+), stats: (?P<stats>\{.*\})\s*$"
)
COUNTERS = (
    ("messages_sent", "messages_sent"),
    ("messages_received", "messages_received"),
    ("connects", "connect_event_count"),
    ("disconnects", "disconnect_event_count"),
    ("pong_count", "pong_count"),
    ("ping_pong_ms_sum", "time_between_ping_pong"),
)


def parse(text):
    totals = {name: 0 for name, _source in COUNTERS}
    seen = False
    for raw in text.splitlines():
        match = LINE.search(raw.strip())
        if not match:
            continue
        try:
            stats = ast.literal_eval(match.group("stats"))
        except (SyntaxError, ValueError) as error:
            raise ValueError(f"could not read stats for {match.group('uid')}: {error}") from error
        if not isinstance(stats, dict):
            raise ValueError(f"stats for {match.group('uid')} were not a dict")
        seen = True
        for name, source in COUNTERS:
            if source not in stats:
                raise ValueError(f"stats are missing {source}")
            totals[name] += int(stats[source])
    if not seen:
        raise ValueError("the load tester printed no per-uid stats")
    mean = None
    if totals["pong_count"]:
        mean = totals["ping_pong_ms_sum"] / totals["pong_count"]
    return {
        "messages_sent": totals["messages_sent"],
        "messages_received": totals["messages_received"],
        "connects": totals["connects"],
        "disconnects": totals["disconnects"],
        "pong_count": totals["pong_count"],
        "ping_pong_ms_sum": totals["ping_pong_ms_sum"],
        "ping_pong_ms_mean": mean,
        "p95_ms": None,
    }


def main(argv):
    text = sys.stdin.read() if not argv else open(argv[0], encoding="utf-8").read()
    json.dump(parse(text), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
