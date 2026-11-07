#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Redact passwords from CI logs before they are printed or uploaded.

TAK's makeCert.sh, openssl and keytool take keystore passwords on the command
line. Falco and container logs can record those command lines, and the
artifacts and job logs of this public repository are readable by anyone
signed in to GitHub. Each deploy generates its own passwords, but they still
do not belong in an artifact.

Usage: redact-logs.py PATH... (files or directories; missing paths are skipped)
Rewrites matching text files in place and prints how many values it replaced.
"""

import os
import re
import sys

MASK = "[REDACTED]"
# A value ends at whitespace, a quote, a backslash (escaped JSON) or a comma.
# An already redacted value is left alone, so a second run changes nothing.
VALUE = r"(?!\[REDACTED\])[^\s\"'\\,]+"
# Credential attributes in rendered TAK config. The value may contain XML
# escapes (&amp; &quot;) and may sit on its own line. clientId and other
# non-secret attributes are left as they are. Single and double quotes both
# occur. A second pass sees [REDACTED] and does not match VALUE-style text
# inside the quotes only when the whole value is already the mask; the
# negative lookahead below keeps a second pass from nesting the mask.
ATTR = r"secret|keystorePass|truststorePass|password"
PATTERNS = (
    # keytool -storepass X, -deststorepass X, -srckeypass X; openssl -key X,
    # -password X, -passin X, -passout X. An openssl "pass:" prefix is kept.
    re.compile(
        r"(-(?:deststorepass|srcstorepass|storepass|destkeypass|srckeypass|keypass|key|password|passin|passout)\s+(?:pass:)?)"
        + VALUE
    ),
    # openssl pass:X anywhere else, for example -passout pass:X.
    re.compile(r"(\bpass:)" + VALUE),
    # <openIdDiscoveryConfiguration ... secret="..."/> and the keystore
    # passwords on <tls> and <connection password="...">, one line or split.
    re.compile(
        rf"(\b(?:{ATTR})\s*=\s*\")(?!\[REDACTED\])[^\"]*(\")"
    ),
    re.compile(
        rf"(\b(?:{ATTR})\s*=\s*')(?!\[REDACTED\])[^']*(')"
    ),
    # curl / form body: client_secret=VALUE
    re.compile(r"(client_secret=)(?!\[REDACTED\])[^\s&\"']+"),
)
SKIP_SUFFIXES = (".gz", ".zip", ".png", ".jpg", ".webm", ".mp4", ".tar", ".zst")


def _mask(match):
    if match.lastindex == 2:
        return match.group(1) + MASK + match.group(2)
    return match.group(1) + MASK


def redact_text(text):
    """Return (text, count) with password and config-secret values replaced by MASK."""
    total = 0
    for pattern in PATTERNS:
        text, count = pattern.subn(_mask, text)
        total += count
    return text, total


def redact_file(path):
    if path.endswith(SKIP_SUFFIXES):
        return 0
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return 0
    if b"\0" in raw[:8192]:
        return 0
    text = raw.decode("utf-8", errors="surrogateescape")
    new, count = redact_text(text)
    if new != text:
        with open(path, "wb") as handle:
            handle.write(new.encode("utf-8", errors="surrogateescape"))
    return count


def walk(path):
    if os.path.isfile(path):
        yield path
        return
    for root, _dirs, files in os.walk(path):
        for name in files:
            yield os.path.join(root, name)


def main(argv):
    # "-" redacts stdin onto stdout and prints no summary, so a log pipe stays
    # a log. "--stdout FILE" does the same for one file and does not rewrite it.
    if argv == ["-"]:
        sys.stdout.write(redact_text(sys.stdin.read())[0])
        return 0
    if len(argv) == 2 and argv[0] == "--stdout":
        with open(argv[1], "rb") as handle:
            raw = handle.read()
        if b"\0" in raw[:8192]:
            sys.stdout.buffer.write(raw)
            return 0
        text = raw.decode("utf-8", errors="surrogateescape")
        sys.stdout.write(redact_text(text)[0])
        return 0
    replaced = 0
    files = 0
    for arg in argv:
        if not os.path.exists(arg):
            continue
        for path in walk(arg):
            count = redact_file(path)
            if count:
                files += 1
                replaced += count
    print(f"redact-logs: replaced {replaced} value(s) in {files} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
