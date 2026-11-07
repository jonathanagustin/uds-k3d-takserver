#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Summarize a rendered CoreConfig without printing secret values.

Stdin is the XML. The report names TLS contexts and says whether each
credential attribute is present, how long it is, and an 8-character sha256
prefix so two copies can be compared. The attribute values are not printed.

    summarize-coreconfig.py --b64

reads a base64 secret (the Secret's data field) on stdin and prints the same
length and prefix. A decode failure prints "unreadable" and not the input.
"""

import base64
import hashlib
import re
import sys

CREDENTIALS = ("secret", "keystorePass", "truststorePass", "password")


def _sha8(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _attr(name, attrs):
    match = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs)
    if match is None:
        match = re.search(rf"\b{name}\s*=\s*'([^']*)'", attrs)
    if match is None:
        return f"{name}=absent"
    value = match.group(1)
    placeholder = "yes" if value.startswith("${") else "no"
    return (
        f"{name}=set length={len(value)} sha8={_sha8(value)} placeholder={placeholder}"
    )


def summarize(xml):
    """Return a multi-line report. Values from xml are never copied into it."""
    if "<" not in xml:
        return "coreconfig: unreadable\n"
    lines = []
    for match in re.finditer(r"<tls\b([^>]*)>", xml, re.DOTALL):
        attrs = match.group(1)
        context = re.search(r'\bcontext\s*=\s*"([^"]*)"', attrs)
        if context is None:
            context = re.search(r"\bcontext\s*=\s*'([^']*)'", attrs)
        lines.append(
            "tls context=" + (context.group(1) if context else "unset")
        )
        for name in ("keystorePass", "truststorePass"):
            lines.append(_attr(name, attrs))
    for match in re.finditer(
        r"<openIdDiscoveryConfiguration\b([^>]*)/?>", xml, re.DOTALL
    ):
        lines.append("openIdDiscovery=present")
        lines.append(_attr("secret", match.group(1)))
    for match in re.finditer(r"<connection\b([^>]*)/?>", xml, re.DOTALL):
        lines.append(_attr("password", match.group(1)))
    if not lines:
        return "coreconfig: no tls, openIdDiscovery, or connection element\n"
    return "\n".join(lines) + "\n"


def summarize_b64(raw):
    raw = raw.strip()
    if not raw:
        return "cluster-secret: unreadable\n"
    try:
        value = base64.b64decode(raw, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return "cluster-secret: unreadable\n"
    return f"cluster-secret length={len(value)} sha8={_sha8(value)}\n"


def main(argv):
    data = sys.stdin.read()
    if argv == ["--b64"]:
        sys.stdout.write(summarize_b64(data))
        return 0
    sys.stdout.write(summarize(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
