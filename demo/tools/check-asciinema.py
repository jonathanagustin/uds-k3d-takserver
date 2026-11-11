#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Check the exact recorder CLI used by deployment before creating a cluster."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess


def check(recorder, output):
    output.mkdir()
    version = subprocess.check_output([str(recorder), '--version'], text=True, timeout=10).strip()
    if version != 'asciinema 2.4.0':
        raise ValueError('recorder version differs')
    exit_file = output / 'recorded.exit'
    cast = output / 'recorded.cast'
    command = 'printf recorder-smoke; exit 0'
    recorded = output / 'recorded-command.sh'
    recorded.write_text('#!/bin/sh\n' + command + '\n')
    # Same flags and shell exit receipt as the real deployment recording.
    args = [str(recorder), 'rec', '--overwrite', '-q', '--cols', '132', '--rows', '34',
            '-c', 'sh ' + shlex.quote(str(recorded)) + '; echo $? > ' + shlex.quote(str(exit_file)), str(cast)]
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                            env={**os.environ, 'TERM':'xterm-256color'})
    if result.returncode != 0 or exit_file.read_text().strip() != '0':
        raise ValueError('recorder command failed')
    rows = [json.loads(line) for line in cast.read_text().splitlines()]
    if (rows[0].get('version') != 2 or rows[0].get('width') != 132 or rows[0].get('height') != 34 or
            'recorder-smoke' not in ''.join(row[2] for row in rows[1:] if row[1] == 'o')):
        raise ValueError('recorder dimensions or captured command differ')
    receipt = {'version':version, 'wheel_sha256':'249ccf108509d643ddaf38979dac48c99e9e251f597173d8553a30d7a6423104',
               'recorder_exit':result.returncode, 'recorded_exit':0, 'cast_version':2, 'width':132, 'height':34}
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.recorder.resolve(strict=True), args.output)
