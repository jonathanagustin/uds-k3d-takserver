#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Live ADR 24 check: revoke one stream while other clients stay connected."""

import base64
import http.client
import json
import os
from pathlib import Path
import select
import socket
import ssl
import subprocess
import sys
import time


def kubectl(*args, data=None):
    return subprocess.run(["uds", "zarf", "tools", "kubectl", *args], input=data,
                          text=True, capture_output=True, check=True, timeout=200).stdout


def snapshot():
    pods = json.loads(kubectl("get", "pods", "-n", "takserver", "-l",
                            "app in (takserver-api,takserver-messaging)", "-o", "json"))["items"]
    assert len(pods) == 2, "API and messaging must each have one pod"
    return sorted((pod["metadata"]["uid"], pod["status"]["startTime"],
                   sorted((s["name"], s["restartCount"]) for s in pod["status"]["containerStatuses"]))
                  for pod in pods)


def event(uid):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 300))
    return (f'<event version="2.0" uid="{uid}" type="a-f-G-U-C" how="m-g" '
            f'time="{now}" start="{now}" stale="{stale}"><point lat="0" lon="0" '
            f'hae="0" ce="9999999" le="9999999"/><detail><contact callsign="{uid}" '
            'endpoint="*:-1:stcp"/></detail></event>').encode()


# Pinned TAK 5.7 exposes historical endpoints by default and caches the active
# query for five seconds. Poll only its explicitly active view; revocation must
# not erase disconnected client history.
ACTIVE_ENDPOINT_PATH = "/Marti/api/clientEndPoints?showCurrentlyConnectedClients=true"


def active_endpoints(admin_ctx, port, domain):
    raw = socket.create_connection(("127.0.0.1", port), timeout=15)
    with admin_ctx.wrap_socket(raw, server_hostname=f"takserver-api.{domain}") as api:
        api.settimeout(5)
        api.sendall((f"GET {ACTIVE_ENDPOINT_PATH} HTTP/1.1\r\nHost: takserver\r\n"
                     "Accept: application/json\r\nConnection: close\r\n\r\n").encode())
        response = http.client.HTTPResponse(api)
        response.begin()
        assert response.status == 200, "admin certificate no longer authenticates"
        payload = json.loads(response.read())
        assert isinstance(payload, dict) and isinstance(payload.get("data"), list), "invalid active endpoint response"
        assert all(isinstance(row, dict) for row in payload["data"]), "invalid active endpoint row"
        assert all(isinstance(row.get("uid"), str) and row["uid"] and
                   (row.get("callsign") is None or isinstance(row["callsign"], str))
                   for row in payload["data"]), "invalid active endpoint identity"
        return payload["data"]


def wait_for_revoked_endpoint(name, fetch, check_controls, *, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + 30
    while True:
        check_controls()
        rows = fetch()  # Authentication, transport and malformed responses fail immediately.
        if not any(row.get("callsign") == name or row.get("uid") == name for row in rows):
            return
        assert clock() < deadline, "revoked callsign remains in active clientEndPoints after 30 seconds"
        sleep(min(1, max(0, deadline - clock())))


def main():
    work, port, name, domain, admin_dir = sys.argv[1:]
    root, port = Path(work), int(port)
    control = f"{name[:54]}-control"
    password = os.environ["TAKCLIENT_KEY_PASS"]
    sockets = []

    def context(cert, key, key_pass=None):
        ctx = ssl.create_default_context(cafile=str(root / "ca.pem"))
        ctx.check_hostname = False  # TAK's streaming cert has no Service SAN.
        ctx.load_cert_chain(str(cert), str(key), password=key_pass)
        return ctx

    client_ctx = context(root / "client.pem", root / "client.key")
    admin_ctx = context(Path(admin_dir) / "admin.pem", Path(admin_dir) / "admin.key", password)

    def connect(ctx, uid):
        raw = socket.create_connection(("127.0.0.1", port), timeout=15)
        try:
            stream = ctx.wrap_socket(raw, server_hostname=f"takserver-stream.{domain}")
        except Exception:
            raw.close()
            raise
        stream.settimeout(5)
        stream.sendall(event(uid))
        return stream

    def read_available(stream):
        if stream.pending() or select.select([stream], [], [], 0)[0]:
            return stream.recv(65536) != b""
        return True

    def cloudtak():
        if kubectl("get", "namespace", "cloudtak", "--ignore-not-found", "-o", "name").strip() and \
                kubectl("get", "deploy", "cloudtak", "-n", "cloudtak", "--ignore-not-found", "-o", "name").strip():
            kubectl("exec", "-n", "cloudtak", "deploy/cloudtak", "-c", "bootstrap", "--",
                    "node", "/home/etl/uds/bootstrap.mjs", "status")

    try:
        kubectl("apply", "-f", "-", data=json.dumps({
            "apiVersion": "tak.jonathanagustin.github.io/v1alpha1", "kind": "TakClient",
            "metadata": {"name": control, "namespace": "takclients"},
            "spec": {"callsign": control, "groups": ["Operators"]},
        }))
        kubectl("wait", "takclient", control, "-n", "takclients", "--for=condition=Ready", "--timeout=180s")
        secret = json.loads(kubectl("get", "secret", control, "-n", "takclients", "-o", "json"))
        for key in ("client.pem", "client.key"):
            (root / f"control-{key}").write_bytes(base64.b64decode(secret["data"][key]))
        control_ctx = context(root / "control-client.pem", root / "control-client.key")
        primary = connect(client_ctx, name)
        survivor = connect(control_ctx, control)
        admin = connect(admin_ctx, "takclient-admin-control")
        sockets.extend([primary, survivor, admin])
        # A rejected or not-yet-registered connection must not count as the
        # live connection closed by revocation.
        for _ in range(4):
            time.sleep(1)
            assert all(read_available(stream) for stream in sockets), "a control stream closed before revoke"
        cloudtak()
        before = snapshot()
        kubectl("delete", "takclient", name, "-n", "takclients", "--timeout=60s")
        deadline = time.monotonic() + 30
        closed = False
        while time.monotonic() < deadline:
            for stream, uid in ((survivor, control), (admin, "takclient-admin-control")):
                assert read_available(stream), "an unrevoked client disconnected"
                stream.sendall(event(uid))
            try:
                if not read_available(primary):
                    closed = True
                    break
            except (ssl.SSLError, OSError):
                closed = True
                break
            time.sleep(0.5)
        assert closed, "revoked live stream stayed connected for 30 seconds"
        print("PASS revoked live stream closed; unrevoked and admin streams stayed connected")

        rejected = False
        try:
            reconnect = connect(client_ctx, name)
            sockets.append(reconnect)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if not read_available(reconnect):
                    rejected = True
                    break
                time.sleep(0.2)
        except (ssl.SSLError, OSError):
            rejected = True
        assert rejected, "revoked certificate reconnected and stayed authenticated"

        def check_controls():
            for stream in (survivor, admin):
                assert read_available(stream), "an unrevoked client disconnected after revoke"
                stream.sendall(event(control if stream is survivor else "takclient-admin-control"))

        wait_for_revoked_endpoint(name, lambda: active_endpoints(admin_ctx, port, domain), check_controls)
        cloudtak()
        assert snapshot() == before, "API or messaging pod UID/start time/restart count changed"
        print("PASS reconnect rejected, active callsign removed, admin/CloudTAK work, and TAK did not restart")
    finally:
        for stream in sockets:
            stream.close()
        kubectl("delete", "takclient", control, "-n", "takclients", "--ignore-not-found", "--wait=false")


if __name__ == "__main__":
    main()
