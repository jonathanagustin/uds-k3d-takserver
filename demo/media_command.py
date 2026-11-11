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


# Production can encode an entire recording; the observed 19-minute assembly
# does not justify a three-minute per-command deadline. Preflight overrides this.
PRODUCTION_SECONDS = 30 * 60


class MediaCommandError(subprocess.CalledProcessError):
    """Catch-compatible failure carrying only sanitized diagnostic text."""
    def __init__(self, returncode, diagnostic):
        super().__init__(returncode, '<media command>', output='', stderr=diagnostic)

    def __str__(self):
        return 'media command failed; see sanitized diagnostic above'


def run_media(command, seconds=None, byte_limit=4 * 1024 * 1024, stdout_limit=32 * 1024 * 1024):
    if seconds is None:
        seconds = float(os.environ.get('DEMO_MEDIA_COMMAND_SECONDS', PRODUCTION_SECONDS))
    if not 0 < seconds <= PRODUCTION_SECONDS:
        raise ValueError('invalid media command budget')
    with tempfile.TemporaryDirectory(prefix='demo-media-') as temporary:
        errors, output = Path(temporary)/'stderr.log', Path(temporary)/'stdout.log'
        complete = False
        diagnostic = ""
        with errors.open('xb') as error, output.open('xb') as stream:
            child = subprocess.Popen(command, stdout=stream, stderr=error, start_new_session=True)
            deadline = time.monotonic() + seconds
            try:
                while child.poll() is None:
                    if (time.monotonic() >= deadline or errors.stat().st_size > byte_limit
                            or output.stat().st_size > stdout_limit):
                        break
                    time.sleep(.05)
                complete = (child.poll() is not None and errors.stat().st_size <= byte_limit
                            and output.stat().st_size <= stdout_limit)
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
                    diagnostic = sanitized.stdout.decode('utf-8', errors='replace')
                else:
                    diagnostic = 'omitted: unsanitizable media stderr\n'
            else:
                diagnostic = 'omitted: media output exceeded its time or size bound\n'
            sys.stderr.write(diagnostic)
            raise MediaCommandError(child.returncode or 1, diagnostic) from None
        return subprocess.CompletedProcess(command, 0, stdout=output.read_text(), stderr=errors.read_text())
