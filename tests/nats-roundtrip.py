#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Core NATS publish and subscribe, the protocol TAK's client uses.

The config below is what NATS chart 1.0.1 renders with clustering and
JetStream off. `server_name: $SERVER_NAME` is the chart's env substitution,
not JSON. NATS 2.15.1 accepts the file when SERVER_NAME is set and
/var/run/nats exists, which the chart's reloader emptyDir provides.
"""

import argparse
import json
import os
import shlex
import socket
import subprocess
import time

# Helm template of nats 1.0.1 with replicaCount 1, cluster off, JetStream off.
CHART_CONFIG = """{
  "http_port": 8222,
  "lame_duck_duration": "30s",
  "lame_duck_grace_period": "10s",
  "pid_file": "/var/run/nats/nats.pid",
  "port": 4222,
  "server_name": $SERVER_NAME
}
"""

SUBJECT = "tak.cluster.roundtrip"
PAYLOAD = b"tak-nats-roundtrip"


def _readline(sock):
    chunks = []
    while True:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("nats connection closed")
        if byte == b"\n":
            break
        chunks.append(byte)
    line = b"".join(chunks)
    if line.endswith(b"\r"):
        line = line[:-1]
    return line


def _readexact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("nats connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _next_line(sock):
    while True:
        line = _readline(sock)
        if line == b"PING":
            sock.sendall(b"PONG\r\n")
            continue
        if line in (b"+OK", b"") or line.startswith(b"INFO "):
            continue
        return line


def roundtrip(host, port, payload=PAYLOAD, timeout=10):
    """Subscribe, publish, and require the same payload back."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        info = _readline(sock)
        if not info.startswith(b"INFO "):
            raise RuntimeError("expected INFO, got %r" % info)
        connect = json.dumps(
            {
                "verbose": False,
                "pedantic": False,
                "lang": "python",
                "version": "1",
                "protocol": 1,
            },
            separators=(",", ":"),
        )
        sock.sendall(("CONNECT %s\r\nPING\r\n" % connect).encode())
        pong = _next_line(sock)
        if pong != b"PONG":
            raise RuntimeError("expected PONG, got %r" % pong)
        sock.sendall(("SUB %s 1\r\n" % SUBJECT).encode())
        sock.sendall(("PUB %s %d\r\n" % (SUBJECT, len(payload))).encode())
        sock.sendall(payload + b"\r\n")
        header = _next_line(sock)
        parts = header.split()
        if len(parts) < 4 or parts[0] != b"MSG" or parts[1] != SUBJECT.encode():
            raise RuntimeError("expected MSG, got %r" % header)
        size = int(parts[-1])
        body = _readexact(sock, size)
        trailer = _readexact(sock, 2)
        if trailer != b"\r\n":
            raise RuntimeError("expected CRLF after payload, got %r" % trailer)
        if body != payload:
            raise RuntimeError("payload mismatch: %r" % body)
        return json.loads(info[5:])


def _kubectl():
    configured = os.environ.get("KUBECTL", "uds zarf tools kubectl")
    return shlex.split(configured)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_forward(namespace, service):
    local = _free_port()
    command = _kubectl() + [
        "-n",
        namespace,
        "port-forward",
        "svc/%s" % service,
        "%d:4222" % local,
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    last_error = None
    while time.time() < deadline:
        if process.poll() is not None:
            err = process.stderr.read().decode(errors="replace")
            raise RuntimeError("port-forward exited: %s" % err.strip())
        try:
            roundtrip("127.0.0.1", local, timeout=2)
            return process, local
        except (OSError, RuntimeError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.5)
    process.kill()
    raise RuntimeError("nats did not accept a client: %s" % last_error)


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_ready(namespace):
    deadline = time.time() + 180
    while time.time() < deadline:
        result = subprocess.run(
            _kubectl()
            + [
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                "app.kubernetes.io/name=nats",
                "-o",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            pods = json.loads(result.stdout).get("items", [])
            for pod in pods:
                if pod.get("metadata", {}).get("deletionTimestamp"):
                    continue
                for condition in pod.get("status", {}).get("conditions", []):
                    if condition.get("type") == "Ready" and condition.get("status") == "True":
                        return
        time.sleep(2)
    raise RuntimeError("nats pod did not become Ready")


def cluster_roundtrip(namespace, service, restart):
    process, port = _port_forward(namespace, service)
    try:
        roundtrip("127.0.0.1", port)
    finally:
        _stop(process)
    if not restart:
        return
    delete = subprocess.run(
        _kubectl()
        + [
            "delete",
            "pod",
            "-n",
            namespace,
            "-l",
            "app.kubernetes.io/name=nats",
            "--wait=true",
        ],
        check=False,
    )
    if delete.returncode != 0:
        raise RuntimeError("failed to delete the nats pod")
    _wait_ready(namespace)
    process, port = _port_forward(namespace, service)
    try:
        roundtrip("127.0.0.1", port)
    finally:
        _stop(process)


def main():
    parser = argparse.ArgumentParser(description="Publish and subscribe on NATS.")
    parser.add_argument("--host", help="Connect here instead of port-forwarding")
    parser.add_argument("--port", type=int, default=4222)
    parser.add_argument("--namespace", default="takserver")
    parser.add_argument("--service", default="takserver-nats")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Delete the NATS pod and publish again after it is Ready",
    )
    args = parser.parse_args()
    if args.host:
        roundtrip(args.host, args.port)
        print("nats roundtrip ok")
        return
    cluster_roundtrip(args.namespace, args.service, args.restart)
    print("nats roundtrip ok")


if __name__ == "__main__":
    main()
