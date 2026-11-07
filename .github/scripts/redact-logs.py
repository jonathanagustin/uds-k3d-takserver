#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Redact passwords and config secrets from CI logs before they are printed.

TAK's makeCert.sh, openssl and keytool take keystore passwords on the command
line. Rendered CoreConfig and JVM options can carry the Keycloak client secret
and the keystore password. This script masks those values. It does not decide
whether a credential outlives the cluster that created it.

Usage:
  redact-logs.py PATH...     rewrite text files in place
  redact-logs.py -           redact stdin onto stdout
  redact-logs.py --stdout F  redact one file onto stdout without rewriting it

A file that contains a NUL or is not valid UTF-8 is not passed through.
Archives, compressed logs, images, and symlinks are not log text this script
can redact. Rewriting replaces each of those with a one-line omission and
exits non-zero. It does not follow a symlink and does not leave the original
bytes in place. Stdout modes print the omission and exit non-zero.
"""

import os
import re
import sys

MASK = "[REDACTED]"
OMITTED = "omitted: unsanitizable file\n"
# A value ends at whitespace, a quote, a backslash (escaped JSON) or a comma.
# An already redacted value is left alone, so a second run changes nothing.
VALUE = r"(?!\[REDACTED\])[^\s\"'\\,]+"
# Credential names in XML, HTML-escaped XML, JSON, env assignments, and -D flags.
# clientId is not in this list.
NAMES = (
    r"secret|keystorePass|truststorePass|password|client_secret|"
    r"TAK_OIDC_CLIENT_SECRET|OIDC_CLIENT_SECRET|TAK_KEYSTORE_PASS|CAPASS"
)
NOT_MASK = r"(?!\[REDACTED\])"
PATTERNS = (
    # keytool -storepass X, -deststorepass X, -srckeypass X; openssl -key X,
    # -password X, -passin X, -passout X. An openssl "pass:" prefix is kept.
    re.compile(
        r"(-(?:deststorepass|srcstorepass|storepass|destkeypass|srckeypass|keypass|key|password|passin|passout)\s+(?:pass:)?)"
        + VALUE,
        re.IGNORECASE,
    ),
    # openssl pass:X anywhere else, for example -passout pass:X.
    re.compile(r"(\bpass:)" + VALUE, re.IGNORECASE),
    # secret="value" and secret='value', including values that contain &amp;
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*\"){NOT_MASK}[^\"]*(\")",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*'){NOT_MASK}[^']*(')",
        re.IGNORECASE,
    ),
    # secret=&quot;value&quot; and secret=&apos;value&apos;
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*&quot;){NOT_MASK}(?:(?!&quot;).)*(&quot;)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*&apos;){NOT_MASK}(?:(?!&apos;).)*(&apos;)",
        re.IGNORECASE,
    ),
    # secret=\"value\" as it appears in JSON and escaped shell logs.
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*\\\"){NOT_MASK}(?:(?!\\\").)*(\\\")",
        re.IGNORECASE,
    ),
    # Unquoted secret=value, TAK_OIDC_CLIENT_SECRET=value, client_secret=value.
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*){NOT_MASK}(?![\"'\\])(?!&quot;)(?!&apos;)[^\s<&'\"\\]+",
        re.IGNORECASE,
    ),
    # -Djavax.net.ssl.keyStorePassword=value and similar JVM system properties.
    re.compile(
        r"(-D[\w.]*?(?:password|passwd|secret|keystorepass|truststorepass)=)"
        + NOT_MASK
        + r"\S+",
        re.IGNORECASE,
    ),
)
# These are not rewritten as text. Leaving them unchanged would publish the
# original bytes from a successful sanitize, so they are omitted instead.
UNSUPPORTED_SUFFIXES = (
    ".gz", ".tgz", ".zip", ".tar", ".zst", ".bz2", ".xz", ".7z",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4",
)


class Unsanitizable(Exception):
    """The bytes are not log text, so they must not be copied through."""


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


def decode_log(raw):
    """Return UTF-8 text, or raise Unsanitizable. Never returns the raw bytes."""
    if b"\0" in raw:
        raise Unsanitizable("nul")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Unsanitizable("utf-8") from exc


def _unsupported_name(path):
    return path.lower().endswith(UNSUPPORTED_SUFFIXES)


def _write_omission(path):
    """Replace path with a regular file. A symlink is removed, not followed."""
    tmp = path + ".omit"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(OMITTED)
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.islink(path):
        os.unlink(path)
    os.replace(tmp, path)


def redact_file(path):
    """Rewrite one file. Return (count, unsafe). Unsafe files keep no original bytes."""
    if os.path.islink(path) or _unsupported_name(path):
        _write_omission(path)
        return 0, True
    if not os.path.isfile(path):
        return 0, False
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return 0, False
    try:
        text = decode_log(raw)
    except Unsanitizable:
        _write_omission(path)
        return 0, True
    new, count = redact_text(text)
    if new != text:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new)
    return count, False


def walk(path):
    """Yield files and symlinks. Do not follow a symlink into another tree."""
    if os.path.islink(path) or os.path.isfile(path):
        yield path
        return
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, followlinks=False):
        linked = []
        for name in dirs:
            candidate = os.path.join(root, name)
            if os.path.islink(candidate):
                linked.append(name)
                yield candidate
        dirs[:] = [name for name in dirs if name not in linked]
        for name in files:
            yield os.path.join(root, name)


def _stdout_bytes(raw):
    try:
        text = decode_log(raw)
    except Unsanitizable:
        sys.stdout.write(OMITTED)
        return 1
    sys.stdout.write(redact_text(text)[0])
    return 0


def main(argv):
    # "-" redacts stdin onto stdout and prints no summary, so a log pipe stays
    # a log. "--stdout FILE" does the same for one file and does not rewrite it.
    # Neither mode prints bytes it could not sanitize.
    if argv == ["-"]:
        return _stdout_bytes(sys.stdin.buffer.read())
    if len(argv) == 2 and argv[0] == "--stdout":
        # A symlink is not opened, so its target is neither printed nor modified.
        if os.path.islink(argv[1]) or _unsupported_name(argv[1]):
            sys.stdout.write(OMITTED)
            return 1
        try:
            with open(argv[1], "rb") as handle:
                raw = handle.read()
        except OSError:
            sys.stdout.write(OMITTED)
            return 1
        return _stdout_bytes(raw)
    replaced = 0
    files = 0
    unsafe = 0
    for arg in argv:
        if not os.path.exists(arg):
            continue
        for path in walk(arg):
            count, bad = redact_file(path)
            if bad:
                unsafe += 1
            elif count:
                files += 1
                replaced += count
    print(f"redact-logs: replaced {replaced} value(s) in {files} file(s)")
    if unsafe:
        print(f"redact-logs: {unsafe} file(s) could not be sanitized", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
