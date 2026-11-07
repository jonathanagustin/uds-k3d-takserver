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
import stat
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
    # [\s\S] crosses newlines. A tail that kept only the second line of an
    # escaped value used to leave that fragment unmatched.
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*&quot;){NOT_MASK}(?:(?!&quot;)[\s\S])*(&quot;)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*&apos;){NOT_MASK}(?:(?!&apos;)[\s\S])*(&apos;)",
        re.IGNORECASE,
    ),
    # secret=\"value\" as it appears in JSON and escaped shell logs.
    re.compile(
        rf"(\b(?:{NAMES})\s*=\s*\\\"){NOT_MASK}(?:(?!\\\")[\s\S])*(\\\")",
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


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError as exc:
        raise Unsanitizable("stat") from exc


def _regular(mode):
    return stat.S_ISREG(mode)


def _write_omission(path):
    """Replace path with a regular file. Do not open a symlink, fifo, or device."""
    tmp = path + ".omit"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(OMITTED)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    except OSError as exc:
        os.unlink(tmp)
        raise Unsanitizable("stat") from exc
    if info is not None and not _regular(info.st_mode):
        os.unlink(path)
    os.replace(tmp, path)


def redact_file(path):
    """Rewrite one file. Return (count, unsafe). Unsafe nodes keep no original bytes.

    A fifo, socket, or device is not opened. A read or stat error is unsafe so
    the caller cannot treat the tree as sanitized.
    """
    info = _lstat(path)
    if not _regular(info.st_mode) or _unsupported_name(path):
        _write_omission(path)
        return 0, True
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        try:
            _write_omission(path)
        except OSError:
            pass
        raise Unsanitizable("read") from exc
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
    """Yield files and non-directories. Do not follow a symlink.

    os.walk ignores listing errors unless onerror is set. A directory that
    cannot be listed would otherwise be marked sanitized with its files unread.
    """
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        yield path
        return
    problems = []

    def onerror(err):
        problems.append(err)

    for root, dirs, files in os.walk(path, followlinks=False, onerror=onerror):
        linked = []
        for name in dirs:
            candidate = os.path.join(root, name)
            try:
                if stat.S_ISLNK(os.lstat(candidate).st_mode):
                    linked.append(name)
                    yield candidate
            except OSError as exc:
                problems.append(exc)
        dirs[:] = [name for name in dirs if name not in linked]
        for name in files:
            yield os.path.join(root, name)
    if problems:
        raise Unsanitizable("walk")


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
        # A symlink, fifo, socket, or device is not opened.
        try:
            info = os.lstat(argv[1])
        except OSError:
            sys.stdout.write(OMITTED)
            return 1
        if not _regular(info.st_mode) or _unsupported_name(argv[1]):
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
        if not os.path.lexists(arg):
            continue
        try:
            paths = list(walk(arg))
        except Unsanitizable:
            print("redact-logs: could not read every log path", file=sys.stderr)
            return 1
        for path in paths:
            try:
                count, bad = redact_file(path)
            except Unsanitizable:
                print("redact-logs: could not read every log path", file=sys.stderr)
                return 1
            if bad:
                # Path only. The original bytes were already replaced.
                print(f"redact-logs: omitted {path}", file=sys.stderr)
                unsafe += 1
            elif count:
                files += 1
                replaced += count
    print(f"redact-logs: replaced {replaced} value(s) in {files} file(s)")
    if unsafe:
        # 2 means the original bytes are gone and an omission stub remains.
        # 1 is reserved for a read or listing failure, where the tree is not safe.
        print(f"redact-logs: {unsafe} file(s) could not be sanitized", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
