#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Normalize owned libtool metadata, without a dos2unix alias or source rewriting."""
import os
from pathlib import Path
import stat
import sys

LIMIT = 1024 * 1024


def normalize(path):
    path = Path(path)
    if path.suffix != '.la':
        raise ValueError('only libtool metadata is supported')
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
            raise ValueError('regular bounded metadata required')
        data = os.read(fd, LIMIT + 1)
        if len(data) != before.st_size or len(data) > LIMIT:
            raise ValueError('metadata size changed')
        text = data.decode('utf-8')
        if ('libtool library file' not in text.split('\n', 1)[0] or
                any(ord(char) < 32 and char not in '\r\n\t' or ord(char) == 127 for char in text)):
            raise ValueError('binary or unrecognized libtool metadata')
        normalized = data.replace(b'\r\n', b'\n')
        if b'\r' in normalized:
            raise ValueError('unexpected bare carriage return')
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(after, name) != getattr(before, name) for name in fields):
            raise ValueError('metadata changed while reading')
        if normalized != data:
            os.lseek(fd, 0, os.SEEK_SET)
            remaining = memoryview(normalized)
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.ftruncate(fd, len(normalized))
            os.fsync(fd)
    finally:
        os.close(fd)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('one owned libtool metadata path required')
    normalize(sys.argv[1])
