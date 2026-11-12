#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Observe an actual Android-shared fixture marker on an explicit TLS TAK peer."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import signal
import ssl
import time
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("scenario", Path(__file__).with_name("android-interoperability.py"))
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)
LIMIT = 1024 * 1024


def observe(stream, markers, deadline):
    """Read only; no CoT transmission, protocol negotiation or replay."""
    pending = b""
    total = 0
    expected = {marker["uid"]: marker for marker in markers}
    observed = set()
    while time.monotonic() < deadline:
        stream.settimeout(max(0.001, min(2, deadline - time.monotonic())))
        try:
            chunk = stream.recv(min(65536, LIMIT - total + 1))
        except socket.timeout:
            continue
        if not chunk:
            raise RuntimeError("peer stream closed before matching marker")
        total += len(chunk)
        if total > LIMIT:
            raise ValueError("peer receive budget exceeded")
        pending += chunk
        if b"<!DOCTYPE" in pending.upper() or b"<!ENTITY" in pending.upper():
            raise ValueError("DTD/entity peer stream rejected")
        while b"</event>" in pending:
            end = pending.index(b"</event>") + len(b"</event>")
            start = pending.find(b"<event")
            payload, pending = pending[start:end] if 0 <= start < end else b"", pending[end:]
            if not payload:
                continue
            if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                raise ValueError("DTD/entity peer event rejected")
            event = ET.fromstring(payload)
            uid = event.get("uid")
            if uid not in expected:
                continue
            point = event.find("point")
            contact = event.find("detail/contact")
            marker = expected[uid]
            if (event.get("type") != marker["type"] or point is None or contact is None
                    or float(point.get("lat")) != marker["lat"]
                    or float(point.get("lon")) != marker["lon"]
                    or contact.get("callsign") != marker["callsign"]):
                raise ValueError("matching UID arrived with different point or callsign")
            observed.add(uid)
            if observed == set(expected):
                return {"received_matching_uids": sorted(observed), "received_bytes": total}
    raise TimeoutError("no matching Android-shared marker within peer deadline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-package", required=True, type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120 or not 1 <= args.port <= 65535:
        parser.error("seconds must be 1..120 and port 1..65535")
    inputs = scenario.inspect_package(args.mission_package)
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = {"package_sha256": inputs["package_sha256"], "status": "failed",
               "execution": "real-tls-observer", "sends_cot": False,
               "remaining": ["verify Android import/map/attachment in UI", "correlate manual Android Share with this observation", "verify reverse-direction update on Android"]}
    def expired(signum, frame):
        raise TimeoutError("overall peer deadline exceeded")
    previous_alarm_handler = signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.seconds)
    started = time.monotonic()
    try:
        context = ssl.create_default_context(cafile=args.ca)
        context.load_cert_chain(args.cert, args.key)
        # Socket connect+TLS+receive share one finite overall deadline.
        deadline = started + args.seconds
        with socket.create_connection((args.host, args.port), timeout=min(10, args.seconds)) as raw:
            raw.settimeout(max(0.001, min(10, deadline - time.monotonic())))
            with context.wrap_socket(raw, server_hostname=args.host) as stream:
                receipt.update(observe(stream, inputs["markers"], deadline))
        receipt["status"] = "peer-observed-matching-cot"
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise SystemExit("peer verification failed: " + type(error).__name__) from None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_alarm_handler)
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
