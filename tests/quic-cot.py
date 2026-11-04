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


def crypto_close(connection):
    """The QUIC CONNECTION_CLOSE code when it is a TLS alert (0x100-0x1ff), else None."""
    event = connection._close_event
    if event is None:
        return None
    print(f"connection closed: error 0x{event.error_code:x} {event.reason_phrase!r}")
    if 0x100 <= event.error_code <= 0x1FF:
        return event.error_code
    return None


async def reject(host, port):
    """Pass only when the server ends the handshake with a TLS alert.

    No answer at all is a failure, so a broken route cannot pass as a refusal.
    In TLS 1.3 the client can finish its side before the server checks the
    client certificate, so a connection that opens is given a few seconds to
    be closed by the server. Data on the stream, or a connection that stays
    open, means the server accepted a client with no certificate.
    """
    loop = asyncio.get_running_loop()
    connection = QuicConnection(configuration=configuration(None, None, None))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: QuicConnectionProtocol(connection),
        sock=sock,
    )
    try:
        protocol.connect((host, port))
        try:
            await asyncio.wait_for(protocol.wait_connected(), 15)
        except TimeoutError:
            print("no QUIC response without a certificate", file=sys.stderr)
            return 1
        except ConnectionError:
            code = crypto_close(connection)
            if code is not None:
                print(f"refused without a certificate: TLS alert {code - 0x100}")
                return 0
            print("connection ended without a TLS alert", file=sys.stderr)
            return 1
        # A stream exists for the server only once a frame carries it.
        reader, writer = await protocol.create_stream()
        writer.write(b"\n")
        try:
            data = await asyncio.wait_for(reader.read(65536), 10)
        except TimeoutError:
            data = b""
        except ConnectionError:
            data = b""
        await asyncio.sleep(0.5)
        code = crypto_close(connection)
        if code is not None and not data:
            print(f"refused without a certificate after the client finished: TLS alert {code - 0x100}")
            return 0
        print(f"no certificate and not refused; {len(data)} bytes on the stream", file=sys.stderr)
        return 1
    finally:
        protocol.close()
        try:
            await asyncio.wait_for(protocol.wait_closed(), 2)
        except TimeoutError:
            pass
        transport.close()


async def roundtrip(host, port, cert, key, password, uid, ready, stop):
    transport = None
    try:
        transport, _protocol, reader, writer = await asyncio.wait_for(
            open_stream(host, port, configuration(cert, key, password)),
            20,
        )
        # Auth is x509 from the client certificate. A QUIC stream reaches the
        # server only with its first data, so TAK starts its handler, and
        # writes its protocol announcement, after the client sends. The
        # client sends its event first. The shell script then checks that
        # /Marti/api/subscriptions/all lists the uid.
        writer.write(cot(uid).encode())
        await writer.drain()
        print(f"sent {uid}")
        reply = await read_until(reader, "TakProtocolSupport", 10)
        if b"TakProtocolSupport" in reply or b"<event" in reply:
            print("TAK answered on the QUIC stream")
        else:
            print("no reply on the QUIC stream yet; the subscription check decides", file=sys.stderr)
        Path(ready).write_text(uid)
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
    parser.add_argument("--pass-file")
    parser.add_argument("--uid")
    parser.add_argument("--ready")
    parser.add_argument("--stop")
    args = parser.parse_args()
    password = None
    if args.mode == "roundtrip":
        if args.pass_file:
            password = Path(args.pass_file).read_text()
        else:
            password = os.environ.get("TAK_CLIENT_KEY_PASSPHRASE", "")
        code = asyncio.run(
            roundtrip(args.host, args.port, args.cert, args.key, password, args.uid, args.ready, args.stop)
        )
    else:
        code = asyncio.run(reject(args.host, args.port))
    return code


if __name__ == "__main__":
    sys.exit(main())
