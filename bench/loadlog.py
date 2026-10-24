#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Read the counters tak_tester.py prints when CloudWatch is off.

The tester adds into a shared array and prints the cumulative dict. The last
line for each uid is that uid's total. A log with no such line is an error,
not a zero.
"""

import ast
import re
import sys

LINE = re.compile(
    r"Info that would be sent to CloudWatch if it was enabled, uid: (?P<uid>\S+), stats: (?P<stats>\{.*\})\s*$"
)
KEYS = (
    "messages_sent",
    "messages_received",
    "connect_count",
    "disconnect_count",
    "pong_count",
    "time_between_ping_pong",
)


def parse(text):
    last = {}
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
        last[match.group("uid")] = stats
    if not last:
        raise ValueError("the load tester printed no per-uid stats")
    totals = {key: 0 for key in KEYS}
    for stats in last.values():
        for key in KEYS:
            if key not in stats:
                raise ValueError(f"stats are missing {key}")
            totals[key] += int(stats[key])
    mean = None
    if totals["pong_count"]:
        mean = totals["time_between_ping_pong"] / totals["pong_count"]
    return {
        "messages_sent": totals["messages_sent"],
        "messages_received": totals["messages_received"],
        "connects": totals["connect_count"],
        "disconnects": totals["disconnect_count"],
        "pong_count": totals["pong_count"],
        "ping_pong_ms_sum": totals["time_between_ping_pong"],
        "ping_pong_ms_mean": mean,
        "p95_ms": None,
    }


def main(argv):
    text = sys.stdin.read() if not argv else open(argv[0], encoding="utf-8").read()
    import json

    json.dump(parse(text), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
