#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bound media-tool output and reveal only complete, redacted failure diagnostics."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def run_media(command, seconds=180, byte_limit=4 * 1024 * 1024):
    with tempfile.TemporaryDirectory(prefix='demo-media-') as temporary:
        errors, output = Path(temporary)/'stderr.log', Path(temporary)/'stdout.log'
        complete = False
        with errors.open('xb') as error, output.open('xb') as stream:
            child = subprocess.Popen(command, stdout=stream, stderr=error, start_new_session=True)
            deadline = time.monotonic() + seconds
            try:
                while child.poll() is None:
                    if time.monotonic() >= deadline or max(errors.stat().st_size, output.stat().st_size) > byte_limit:
                        break
                    time.sleep(.05)
                complete = child.poll() is not None and max(errors.stat().st_size, output.stat().st_size) <= byte_limit
            finally:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        if child.returncode != 0 or not complete:
            if complete:
                redactor = Path(__file__).resolve().parents[1]/'.github/scripts/redact-logs.py'
                sanitized = subprocess.run([sys.executable, str(redactor), '--stdout', str(errors)],
                                           capture_output=True, timeout=15)
                if sanitized.returncode == 0:
                    # Text avoids an unredacted command/argument dump from CalledProcessError.
                    sys.stderr.write(sanitized.stdout.decode('utf-8', errors='replace'))
                else:
                    print('omitted: unsanitizable media stderr', file=sys.stderr)
            else:
                print('omitted: media output exceeded its time or size bound', file=sys.stderr)
            raise RuntimeError('media command failed; see sanitized diagnostic above')
        return subprocess.CompletedProcess(command, 0, stdout=output.read_text(), stderr='')
