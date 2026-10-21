#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Require server acceptance of the retained certificate on the 8089 gateway."""

import argparse
import socket
import ssl


def connect(port, cert=None, key=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The local test cluster uses a generated CA. This tests client authentication.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # TLS 1.3 can return from the client handshake before a rejection arrives.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    if cert:
        context.load_cert_chain(cert, key, password="atakatak")
    with socket.create_connection(("127.0.0.1", port), timeout=20) as raw:
        with context.wrap_socket(raw, server_hostname="takserver-stream.uds.dev") as stream:
            if stream.version() != "TLSv1.2":
                raise RuntimeError("8089 did not negotiate TLS 1.2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    connect(args.port, args.cert, args.key)
    print("PASS 8089 accepted the pre-upgrade client certificate")
    try:
        connect(args.port)
    except ssl.SSLError as error:
        if not any(reason in str(error).upper() for reason in (
            "CERTIFICATE_REQUIRED", "HANDSHAKE_FAILURE", "BAD_CERTIFICATE",
        )):
            raise
        print("PASS 8089 explicitly rejected a connection without a certificate")
    else:
        raise RuntimeError("8089 accepted a connection without a client certificate")


if __name__ == "__main__":
    main()
