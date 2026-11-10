#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise actual desktop storage plus source-pinned metadata contracts."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='takx-platform-') as temporary:
    work = Path(temporary)
    sources = [ROOT / 'src/main/java' / name for name in (
        'android/os/Environment.java', 'android/util/Patterns.java',
        'android/annotation/SuppressLint.java')]
    subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-d',
                    str(work / 'classes'), *map(str, sources),
                    str(ROOT / 'src/test/java/PlatformServicesCompatibilityTest.java')],
                   check=True, timeout=30)
    # A caller's configured storage must not affect these isolated filesystem tests.
    environment = dict(os.environ)
    environment.pop('TAK_EXTERNAL_STORAGE', None)
    subprocess.run(['java', '-ea', '-cp', str(work / 'classes'),
                    'PlatformServicesCompatibilityTest', str(work)],
                   env=environment, check=True, timeout=30)
