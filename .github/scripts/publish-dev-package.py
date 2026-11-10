#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""One upstream publication invocation, bounded with its owned descendants."""
import os
import signal
import subprocess
import sys

PUBLICATION_SECONDS = 1200
TERMINATION_SECONDS = 10


def publish(archive, repository, tag, seconds=PUBLICATION_SECONDS, grace=TERMINATION_SECONDS):
    command = ['uds', 'zarf', 'package', 'publish', archive, repository,
               '--tag', tag, '--retries', '3', '--confirm', '--no-progress']
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        try:
            result = child.wait(timeout=seconds)
            return result if result >= 0 else 128 - result
        except subprocess.TimeoutExpired:
            print('dev-package: publication deadline exceeded', file=sys.stderr)
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            return 124
    finally:
        # Also clean descendants when the publisher itself has already exited.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def main():
    if len(sys.argv) != 4:
        print('usage: publish-dev-package.py ARCHIVE OCI_REPOSITORY INPUT_KEY', file=sys.stderr)
        return 2
    def interrupted(number, _frame):
        raise SystemExit(128 + number)
    previous = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        try:
            return publish(*sys.argv[1:])
        except OSError:
            print('dev-package: publication process unavailable', file=sys.stderr)
            return 127
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    sys.exit(main())
