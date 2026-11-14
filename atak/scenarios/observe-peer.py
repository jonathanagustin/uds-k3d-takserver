#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Observe an actual Android-shared fixture marker on an explicit TLS TAK peer."""
import argparse
import contextlib
import datetime
import hashlib
import re
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


@contextlib.contextmanager
def open_peer(args, deadline):
    context = ssl.create_default_context(cafile=args.ca)
    pin = getattr(args, "server_leaf_sha256", None)
    if pin:
        if not re.fullmatch("[0-9a-f]{64}", pin):
            raise ValueError("invalid deployment leaf pin")
        # Explicit CA+leaf identity mode. Chain validation remains mandatory;
        # pin is extracted from authenticated deployment data, never the wire.
        context.check_hostname = False
    if context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("peer requires CA verification")
    context.load_cert_chain(args.cert, args.key)
    with socket.create_connection((getattr(args, "connect_host", None) or args.host, args.port), timeout=min(10, max(.001, deadline-time.monotonic()))) as raw:
        raw.settimeout(max(.001, min(10, deadline-time.monotonic())))
        with context.wrap_socket(raw, server_hostname=args.host) as stream:
            if pin and hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest() != pin:
                raise ValueError("deployment leaf mismatch")
            yield stream


def write_control(path, payload):
    with path.open("x") as stream:
        json.dump(payload, stream)


def share_fence(stream, directory, deadline):
    """Drain before Share; only the Android UI controller writes share.json."""
    discarded = 0
    write_control(directory / "ready.json", {"ready": True})
    quiet_since = time.monotonic()
    armed = False
    while time.monotonic() < deadline:
        if (directory / "prepare.json").exists() and not armed and time.monotonic()-quiet_since >= .5:
            write_control(directory / "armed.json", {"armed": True})
            armed = True
        if armed and (directory / "share.json").exists():
            cutoff = json.loads((directory / "share.json").read_text())["android_not_before"]
            if not isinstance(cutoff, int) or cutoff <= 0:
                raise ValueError("invalid Android time fence")
            return cutoff, discarded
        stream.settimeout(.1)
        try:
            chunk = stream.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            raise RuntimeError("peer closed before Share")
        discarded += len(chunk)
        if discarded > LIMIT:
            raise ValueError("pre-share receive budget exceeded")
        quiet_since = time.monotonic()
    raise TimeoutError("Share readiness deadline")


def observe(stream, markers, deadline, not_before=None):
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
            if not_before is not None:
                stamp = datetime.datetime.fromisoformat(event.get("time", "").replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("event time has no zone")
                if stamp.timestamp() < not_before:
                    continue
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
                return {"received_matching_uids": sorted(observed), "received_bytes": total,
                        "fresh_event_time": event.get("time"), "android_not_before": not_before}
    raise TimeoutError("no matching Android-shared marker within peer deadline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-package", required=True, type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--connect-host")
    parser.add_argument("--server-leaf-sha256")
    parser.add_argument("--challenge", help="8 lowercase hex digits edited only through Android UI")
    parser.add_argument("--control", type=Path)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120 or not 1 <= args.port <= 65535:
        parser.error("seconds must be 1..120 and port 1..65535")
    inputs = scenario.inspect_package(args.mission_package)
    if args.challenge:
        if not re.fullmatch("[0-9a-f]{8}", args.challenge) or args.control is None:
            parser.error("challenge requires eight hex digits and control directory")
        for marker in inputs["markers"]:
            marker["callsign"] += " " + args.challenge
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
        deadline = started + args.seconds
        with open_peer(args, deadline) as stream:
            cutoff = None
            if args.control:
                cutoff, discarded = share_fence(stream, args.control, deadline)
                receipt["pre_share_discarded_bytes"] = discarded
            receipt.update(observe(stream, inputs["markers"], deadline, cutoff))
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
