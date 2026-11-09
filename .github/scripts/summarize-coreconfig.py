#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Summarize a rendered CoreConfig without printing secret values.

Stdin is the XML. The report names TLS contexts and says whether each
credential attribute is absent, a ${} placeholder, or present. It does not
print the value, its length, or a hash.

    summarize-coreconfig.py --b64

reads a base64 secret (the Secret's data field) on stdin and prints only
present, absent, or unreadable. A decode failure does not echo the input.
"""

import base64
import re
import sys


def _attr(name, attrs):
    match = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs)
    if match is None:
        match = re.search(rf"\b{name}\s*=\s*'([^']*)'", attrs)
    if match is None:
        return f"{name}=absent"
    value = match.group(1)
    if value.startswith("${") or value == "":
        return f"{name}=placeholder" if value.startswith("${") else f"{name}=absent"
    return f"{name}=present"


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
        return "cluster-secret=absent\n"
    try:
        value = base64.b64decode(raw, validate=True)
    except ValueError:
        return "cluster-secret=unreadable\n"
    if not value:
        return "cluster-secret=absent\n"
    return "cluster-secret=present\n"


def main(argv):
    data = sys.stdin.read()
    if argv == ["--b64"]:
        sys.stdout.write(summarize_b64(data))
        return 0
    sys.stdout.write(summarize(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
