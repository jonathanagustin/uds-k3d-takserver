#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Speak TAK's QUIC streaming protocol.

TAK 5.7-RELEASE-14 builds the QUIC server with ClientAuth.REQUIRE and ALPN
takstream (NioNettyInitializer.buildQuicServerSslContext). The input's auth
attribute defaults to x509. This client opens one bidirectional stream.

The server certificate is the TAK keystore certificate, not a name for the
gateway address, so the client does not check that name. A missing client
certificate must fail the handshake. That is the check the server enforces.

Run it inside the cluster network. kubectl port-forward does not carry UDP.
"""

import argparse
import asyncio
import os
import socket
import ssl
import sys
import time
from pathlib import Path

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection


def configuration(cert, key, password):
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["takstream"],
        verify_mode=ssl.CERT_NONE,
        server_name="takserver",
        idle_timeout=30.0,
    )
    if cert:
        config.load_cert_chain(cert, key, password or None)
    return config


async def open_stream(host, port, config):
    loop = asyncio.get_running_loop()
    connection = QuicConnection(configuration=config)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: QuicConnectionProtocol(connection),
        sock=sock,
    )
    protocol.connect((host, port))
    await protocol.wait_connected()
    reader, writer = await protocol.create_stream()
    return transport, protocol, reader, writer


def cot(uid):
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    stale = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 300))
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><event version="2.0" uid="{uid}" '
        f'type="a-f-G-U-C" how="m-g" time="{now}" start="{now}" stale="{stale}">'
        f'<point lat="0" lon="0" hae="0" ce="9999999" le="9999999"/>'
        f'<detail><contact callsign="{uid}" endpoint="*:-1:quic"/>'
        f'<takv platform="uds-quic" version="1"/></detail></event>'
    )


async def read_until(reader, needle, timeout):
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        left = deadline - time.monotonic()
        try:
            chunk = await asyncio.wait_for(reader.read(65536), min(left, 5))
        except TimeoutError:
            continue
        if not chunk:
            break
        buf += chunk
        if needle.encode() in buf:
            return buf
    return buf


async def reject(host, port):
    transport = None
    try:
        transport, _protocol, _reader, _writer = await asyncio.wait_for(
            open_stream(host, port, configuration(None, None, None)),
            15,
        )
    except Exception as exc:
        print(f"refused without a certificate: {type(exc).__name__}")
        return 0
    finally:
        if transport is not None:
            transport.close()
    print("handshake succeeded without a client certificate", file=sys.stderr)
    return 1


async def roundtrip(host, port, cert, key, password, uid, ready, stop):
    transport = None
    try:
        transport, _protocol, reader, writer = await asyncio.wait_for(
            open_stream(host, port, configuration(cert, key, password)),
            20,
        )
        # Auth is x509 from the client certificate. The server then writes a
        # CoT protocol announcement (TakProtocolSupport) on the stream.
        announcement = await read_until(reader, "TakProtocolSupport", 20)
        if b"TakProtocolSupport" not in announcement and b"<event" not in announcement:
            print("no CoT event on the QUIC stream", file=sys.stderr)
            print(announcement[:500], file=sys.stderr)
            return 1
        writer.write(cot(uid).encode())
        await writer.drain()
        Path(ready).write_text(uid)
        print(f"sent {uid}")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not Path(stop).exists():
            await asyncio.sleep(0.5)
        return 0
    except Exception as exc:
        print(f"QUIC round trip failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if transport is not None:
            transport.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("reject", "roundtrip"))
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--uid")
    parser.add_argument("--ready")
    parser.add_argument("--stop")
    args = parser.parse_args()
    password = None
    if args.mode == "roundtrip":
        password = os.environ.get("TAK_CLIENT_KEY_PASSPHRASE", "")
        code = asyncio.run(
            roundtrip(args.host, args.port, args.cert, args.key, password, args.uid, args.ready, args.stop)
        )
    else:
        code = asyncio.run(reject(args.host, args.port))
    return code


if __name__ == "__main__":
    sys.exit(main())
