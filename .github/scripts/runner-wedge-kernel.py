#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Collect bounded local kernel evidence; SysRq-w only after a routing timeout."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wedge_redactor', HERE / 'redact-logs.py')
redactor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redactor)
LIMIT = 8 * 1024 * 1024


def capture(argv, seconds, deadline):
    """Private file descriptors prevent stuck children retaining Actions pipes."""
    if time.monotonic() >= deadline:
        return None, 'deadline'
    def limits():
        os.umask(0o077)
        resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out,
                                   stderr=err, start_new_session=True, preexec_fn=limits)
        end = min(deadline, time.monotonic() + seconds)
        failure = None
        try:
            while process.poll() is None:
                if time.monotonic() >= end:
                    failure = 'timeout'
                    break
                if out.tell() + err.tell() >= LIMIT:
                    failure = 'output-limit'
                    break
                time.sleep(.02)
            if out.tell() + err.tell() >= LIMIT:
                failure = 'output-limit'
            if failure is None and process.returncode != 0:
                failure = 'command-failed'
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # A D-state task may ignore KILL. Never wait for it indefinitely.
            try:
                process.wait(timeout=.1)
            except subprocess.TimeoutExpired:
                failure = failure or 'unreaped-kernel-task'
        if failure:
            return None, failure
        out.seek(0)
        err.seek(0)
        raw = out.read(LIMIT + 1) + err.read(LIMIT + 1)
        try:
            text = raw.decode('utf-8', errors='strict')
            if '\0' in text:
                raise ValueError('binary stream')
            # Redact the complete stream before extracting or printing lines.
            return redactor.redact_text(text)[0], 'complete'
        except (UnicodeError, ValueError):
            return None, 'unsanitizable'


def collect(network_stalled, state_root, emit=print):
    deadline = time.monotonic() + 11
    def run(label, argv, seconds):
        try:
            text, status = capture(argv, seconds, deadline)
        except OSError:
            text, status = None, 'unavailable'
        return label, text, status
    before = run('dmesg-before', ['sudo', '-n', 'dmesg', '-T'], 3)
    hung = before[1] is not None and re.search(
        r'blocked for more than [0-9]+ seconds|hung_task|rtnl_lock', before[1]) is not None
    wedged = network_stalled or hung
    if wedged:
        emit('Kernel hung-task evidence (complete streams redacted before output):')
        version = os.environ.get('ImageVersion', 'unknown')
        version = version if re.fullmatch(r'[0-9.]+', version) else 'unknown'
        emit('kernel=' + os.uname().release + ' ImageVersion=' + version)
        results = [before]
        if network_stalled:
            # mkdir is atomic across repeated probes in this job. A failed
            # trigger is not retried: kernel-state collection stays one-shot.
            claim = state_root / 'runner-wedge-sysrq-w'
            try:
                claim.mkdir(mode=0o700)
                claimed = True
            except FileExistsError:
                claimed = False
            if claimed:
                results.append(run('sysrq-w', ['sudo', '-n', 'sh', '-c',
                                               'printf w > /proc/sysrq-trigger'], 2))
                results.append(run('dmesg-after-sysrq-w', ['sudo', '-n', 'dmesg', '-T'], 3))
            else:
                emit('sysrq-w: already claimed in this job; no repeated trigger')
        results.append(run('lsmod', ['lsmod'], 2))
        for label, text, status in results:
            emit(label + ': ' + status)
            if text is not None:
                # Preserve full call traces, not ten grep-matched header lines.
                emit(text)
        emit('::warning::Routing or kernel evidence matches the runner stall investigated in issue #300; the cause remains unproven. Preserve this run for https://github.com/jonathanagustin/uds-takserver/issues/300.')
    else:
        emit('dmesg-before: ' + before[2])
        emit('No sign of the #300 runner wedge.' if before[1] is not None
             else 'Kernel evidence is inconclusive; no runner cause is established.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network-stalled', choices=['true', 'false'], required=True)
    args = parser.parse_args()
    # RUNNER_TEMP is job-private on hosted runners. A stable marker there
    # survives repeated helper invocations without making another SysRq call.
    state = Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir()))
    def interrupted(signum, frame):
        raise TimeoutError('outer collection deadline')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        collect(args.network_stalled == 'true', state)
    except (OSError, TimeoutError):
        print('Kernel evidence collection incomplete; routing result is unchanged.')


if __name__ == '__main__':
    main()
