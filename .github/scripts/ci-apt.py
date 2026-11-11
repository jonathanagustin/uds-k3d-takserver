#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bound signed CI package acquisition; one exact Ubuntu HTTPS fallback, no stale success."""
import argparse
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

CONFIG = b'''// Owned CI acquisition bounds; signature and TLS verification remain enabled.
Acquire::Retries "0";
Acquire::http::Timeout "10";
Acquire::https::Timeout "10";
APT::Update::Error-Mode "any";
DPkg::Lock::Timeout "15";
'''
OPTIONS = ['-o', 'Acquire::Retries=0', '-o', 'Acquire::http::Timeout=10',
           '-o', 'Acquire::https::Timeout=10', '-o', 'APT::Update::Error-Mode=any',
           '-o', 'DPkg::Lock::Timeout=15']
MIRRORS = {'azure.archive.ubuntu.com':'archive.ubuntu.com',
           'archive.ubuntu.com':'archive.ubuntu.com', 'security.ubuntu.com':'security.ubuntu.com'}
MIRROR_FILES = {'apt-mirrors.txt', 'apt-mirrors-security.txt'}
MAX_FILE = 256 * 1024


def read_regular(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('APT path contains a symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise ValueError('APT input is not a bounded regular file')
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('APT input exceeds bound')
    return data, info


def canonical_uri(uri):
    try:
        value = urlsplit(uri)
        if (value.scheme != 'http' or value.username is not None or value.password is not None or
                value.port is not None or value.hostname not in MIRRORS or value.path not in ('/ubuntu','/ubuntu/') or
                value.query or value.fragment):
            return uri
        return 'https://' + MIRRORS[value.hostname] + value.path
    except ValueError:
        return uri


def rewrite(data, kind):
    lines, in_uris = [], False
    for line in data.decode('utf-8').splitlines(keepends=True):
        if kind == 'list':
            match = re.match(r'^(\s*deb(?:-src)?\s+(?:\[[^\]\r\n]*\]\s+)?)(\S+)', line)
            if match:
                line = line[:match.start(2)] + canonical_uri(match[2]) + line[match.end(2):]
        elif kind == 'sources':
            if not line.strip():
                in_uris = False
            elif not line.lstrip().startswith('#'):
                field = re.match(r'^([^\s:]+):', line)
                if field:
                    in_uris = field[1].lower() == 'uris'
                if in_uris:
                    start = field.end() if field else 0
                    line = line[:start] + re.sub(r'\S+', lambda m: canonical_uri(m[0]), line[start:])
        elif kind == 'mirror' and not line.lstrip().startswith('#'):
            match = re.match(r'^(\s*)(\S+)', line)
            if match:
                line = line[:match.start(2)] + canonical_uri(match[2]) + line[match.end(2):]
        lines.append(line)
    return ''.join(lines).encode('utf-8')


def source_files(root):
    if root.is_symlink() or (root/'sources.list.d').is_symlink():
        raise ValueError('ordinary APT directories required')
    files = []
    for path in [root/'sources.list', *sorted((root/'sources.list.d').glob('*')), *(root/n for n in sorted(MIRROR_FILES))]:
        if path.is_symlink():
            raise ValueError('APT source symlink refused')
        if not path.exists():
            continue
        kind = 'list' if path.name == 'sources.list' or path.suffix == '.list' else 'sources' if path.suffix == '.sources' else 'mirror' if path.name in MIRROR_FILES else None
        if kind:
            data, info = read_regular(path)
            files.append((path, data, info, kind))
    if len(files) > 64:
        raise ValueError('too many APT source files')
    return files


def atomic_replace(path, data, info=None):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('APT write path contains a symlink')
    fd, name = tempfile.mkstemp(prefix='.uds-ci-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) if info else 0o644)
            if info and os.geteuid() == 0:
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def fallback(root):
    changes = [(p, before, rewrite(before, kind), info) for p,before,info,kind in source_files(root)]
    changes = [row for row in changes if row[1] != row[2]]
    # Validate the entire plan before publishing; roll back owned changes if a write fails.
    for path, before, _, _ in changes:
        if read_regular(path)[0] != before:
            raise ValueError('APT source changed while planning')
    done = []
    try:
        for path, before, after, info in changes:
            if read_regular(path)[0] != before:
                raise ValueError('APT source changed before replacement')
            atomic_replace(path, after, info); done.append((path,before,after,info))
    except BaseException:
        for path,before,after,info in reversed(done):
            if read_regular(path)[0] == after:
                atomic_replace(path,before,info)
        raise
    print(f'ci-apt: changed {len(changes)} recognized Ubuntu source files to HTTPS')
    return bool(changes)


def configure(root):
    directory = root/'apt.conf.d'
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('ordinary apt.conf.d required')
    path = directory/'99zz-uds-ci-acquisition'
    if path.exists() or path.is_symlink():
        if read_regular(path)[0] != CONFIG:
            raise ValueError('owned APT bound configuration differs')
    else:
        atomic_replace(path, CONFIG)


def scrub_uri_credentials(text):
    # APT may echo authenticated/custom URLs; preserve their configuration, not
    # credentials in their diagnostic spelling. Run on the complete capture.
    return re.sub(r"(?i)\b(?:https?|ftp)://[^\s<>\"']+",
                  lambda match: '[REDACTED URL]' if '@' in match[0] or '?' in match[0] else match[0], text)


def run_apt(operation, packages=(), seconds=None):
    if seconds is None:
        seconds = 60 if operation == 'update' else 120
    command = ['apt-get', *OPTIONS, operation]
    if operation == 'install':
        command += ['-y', '-o', 'Dpkg::Use-Pty=0', '--no-install-recommends', *packages]
    with tempfile.TemporaryDirectory(prefix='uds-ci-apt-') as temporary:
        log = Path(temporary)/'apt.log'
        with log.open('xb') as output:
            child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, 'DEBIAN_FRONTEND':'noninteractive','NEEDRESTART_MODE':'a'}, start_new_session=True)
            try:
                deadline = time.monotonic() + seconds
                while child.poll() is None and time.monotonic() < deadline and log.stat().st_size <= 4*1024**2:
                    time.sleep(.05)
                code = child.poll()
                if code is None or log.stat().st_size > 4*1024**2:
                    code = 124
            finally:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
        # Never publish incomplete or oversized logs, or exception strings containing source credentials.
        if code != 124 and log.stat().st_size <= 4*1024**2:
            log.write_text(scrub_uri_credentials(log.read_text()))
            subprocess.run([sys.executable, str(Path(__file__).with_name('redact-logs.py')), '--stdout', str(log)], check=True, timeout=10)
        else:
            print('ci-apt: omitted incomplete or oversized package-manager log')
        return code


def update(root, runner=run_apt):
    configure(root)
    source_files(root)  # Reject unsafe paths before running the package manager.
    if runner('update') == 0:
        return 0
    if not fallback(root):
        print('ci-apt: update failed; no recognized Ubuntu HTTP source to change')
        return 1
    if runner('update') == 0:
        return 0
    print('ci-apt: both signed updates failed; infrastructure acquisition unavailable; no install allowed')
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('update','install'))
    parser.add_argument('packages', nargs='*')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo on the ephemeral CI runner')
    if args.operation == 'update':
        if args.packages: parser.error('update takes no packages')
        return update(Path('/etc/apt'))
    if not args.packages or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:-]*', p) for p in args.packages):
        parser.error('install requires literal package names, not flags or URIs')
    configure(Path('/etc/apt'))
    return run_apt('install',args.packages)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print('ci-apt: acquisition configuration or command failed; no insecure fallback', file=sys.stderr)
        raise SystemExit(1) from None
