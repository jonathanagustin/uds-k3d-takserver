#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Audit installed browser ELFs; acquire only observed missing runtime libraries."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

# Playwright v1.65.0 nativeDeps.ts, ubuntu24.04-x64 chromium/lib2package.
# No fonts, optional tool packages, arbitrary package names or alternate mirrors.
PACKAGES = {'libX11.so.6': 'libx11-6',
 'libXcomposite.so.1': 'libxcomposite1',
 'libXdamage.so.1': 'libxdamage1',
 'libXext.so.6': 'libxext6',
 'libXfixes.so.3': 'libxfixes3',
 'libXrandr.so.2': 'libxrandr2',
 'libasound.so.2': 'libasound2t64',
 'libatk-1.0.so.0': 'libatk1.0-0t64',
 'libatk-bridge-2.0.so.0': 'libatk-bridge2.0-0t64',
 'libatspi.so.0': 'libatspi2.0-0t64',
 'libcairo.so.2': 'libcairo2',
 'libcups.so.2': 'libcups2t64',
 'libdbus-1.so.3': 'libdbus-1-3',
 'libdrm.so.2': 'libdrm2',
 'libgbm.so.1': 'libgbm1',
 'libgio-2.0.so.0': 'libglib2.0-0t64',
 'libglib-2.0.so.0': 'libglib2.0-0t64',
 'libgmodule-2.0.so.0': 'libglib2.0-0t64',
 'libgobject-2.0.so.0': 'libglib2.0-0t64',
 'libnspr4.so': 'libnspr4',
 'libnss3.so': 'libnss3',
 'libnssutil3.so': 'libnss3',
 'libpango-1.0.so.0': 'libpango-1.0-0',
 'libsmime3.so': 'libnss3',
 'libxcb.so.1': 'libxcb1',
 'libxkbcommon.so.0': 'libxkbcommon0'}
HERE = Path(__file__).resolve().parent


class PreflightError(ValueError):
    """Only fixed, non-secret diagnostic reasons are emitted."""


def run(command, cwd, seconds=30, env=None):
    """Capture both streams privately and redact the whole bounded capture first."""
    with tempfile.TemporaryDirectory(prefix='docs-browser-') as temporary:
        log = Path(temporary)/'output'
        with log.open('xb') as output:
            child = subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True, env=env)
            try:
                end = time.monotonic()+seconds
                while child.poll() is None and time.monotonic()<end and log.stat().st_size<=1024**2:
                    time.sleep(.05)
                if child.poll() is None or log.stat().st_size>1024**2:
                    raise PreflightError('browser command exceeded time or output limit')
            finally:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
        # Redaction failure is fatal; no raw process errors or arguments printed.
        clean = subprocess.run([sys.executable, str(HERE/'redact-logs.py'), '--stdout', str(log)],
                               capture_output=True, check=True, timeout=10)
        return child.returncode, clean.stdout.decode('utf-8', errors='strict')


def elf_files(paths):
    if len(paths)!=2 or len(set(paths))!=2:
        raise PreflightError('two distinct locked browser executables required')
    files = set()
    for value in paths:
        executable = Path(value)
        if not executable.is_absolute() or not executable.is_file():
            raise PreflightError('locked browser executable missing')
        root = executable.parent.resolve()
        for count,path in enumerate(root.rglob('*')):
            if count>=2048:
                raise PreflightError('too many browser distribution entries')
            if path.is_symlink():
                if not path.resolve().is_relative_to(root):
                    raise PreflightError('browser child escapes distribution')
                continue
            if path.is_file():
                with path.open('rb') as stream:
                    if stream.read(4)==b'\x7fELF': files.add(path)
            if len(files)>128:
                raise PreflightError('too many browser ELF children')
        if executable not in files:
            raise PreflightError('locked executable is not ELF')
    return sorted(files)


def missing_packages(files, cwd):
    missing = set()
    deadline = time.monotonic()+30
    for path in files:
        remaining = deadline-time.monotonic()
        if remaining<=0: raise PreflightError('browser ELF audit exceeded deadline')
        environment = {**os.environ, 'LD_LIBRARY_PATH':str(path.parent)}
        code, output = run(['ldd', str(path)], cwd, min(5,remaining), environment)
        if code and output.strip() not in ('not a dynamic executable', 'statically linked'):
            print(output, end='')
            raise PreflightError('ldd could not audit browser distribution')
        for line in output.splitlines():
            if 'not found' not in line:
                continue
            match = re.fullmatch(r'\s*([A-Za-z0-9_.+-]+)\s+=>\s+not found\s*', line)
            if not match or match[1] not in PACKAGES:
                print(output, end='')
                raise PreflightError('unrecognized missing browser library')
            missing.add(PACKAGES[match[1]])
    return sorted(missing)


def qualify(project):
    code, output = run(['node', str(HERE/'docs-browser-smoke.cjs'), 'paths'], project)
    if code:
        print(output, end='')
        raise PreflightError('locked Playwright executable discovery failed')
    paths = json.loads(output)
    if not isinstance(paths,list) or any(not isinstance(p,str) for p in paths):
        raise PreflightError('invalid locked browser paths')
    files = elf_files(paths)
    packages = missing_packages(files, project)
    if packages:
        # Exactly one update path and one install. ci-apt owns signed/HTTPS bounds.
        for operation in [('update',), ('install',*packages)]:
            code, output = run(['sudo', sys.executable, str(HERE/'ci-apt.py'), *operation], project, 135)
            print(output, end='')
            if code: raise PreflightError('bounded browser dependency acquisition failed')
        if missing_packages(files, project):
            raise PreflightError('browser dependencies still missing after one install')
    code, output = run(['node', str(HERE/'docs-browser-smoke.cjs'), 'launch'], project, 45)
    print(output, end='')
    if code: raise PreflightError('real browser launch failed; no speculative APT retry')
    print(f'Docs browser: {len(files)} ELF files audited; real launches passed')


if __name__=='__main__':
    try:
        qualify(Path.cwd())
    except PreflightError as error:
        print(f'Docs browser preflight failed: {error}', file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Docs browser preflight failed; no unchecked dependency fallback', file=sys.stderr)
        raise SystemExit(1) from None
