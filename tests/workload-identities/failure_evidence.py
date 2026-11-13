# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""First-failure callsites only: never exception messages, locals or command output."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FILES = frozenset('tests/workload-identities/' + name for name in (
    'package_roundtrip.py', 'drive.py', 'phase_evidence.py', 'render_inputs.py',
    'retained_state.py', 'failure_evidence.py')) | {'tests/ephemeral-cluster.py'}
LIMIT = 16384
MAX_FRAMES = 16
NAME = 'PRIVATE-failure-callsite.json'
TYPES = frozenset(('ValueError', 'KeyError', 'TypeError', 'AttributeError', 'OSError',
                  'FileNotFoundError', 'PermissionError', 'TimeoutError', 'TimeoutExpired',
                  'CalledProcessError', 'JSONDecodeError', 'EvidenceError', 'RuntimeError'))


def identity():
    result = {field: os.environ.get(env, '') for field, env in
              [('sourceSHA', 'GITHUB_SHA'), ('runID', 'GITHUB_RUN_ID'), ('runAttempt', 'GITHUB_RUN_ATTEMPT')]}
    if not (re.fullmatch('[a-f0-9]{40}', result['sourceSHA'])
            and all(re.fullmatch('[1-9][0-9]{0,19}', result[key]) for key in ('runID', 'runAttempt'))):
        raise ValueError('invalid failure identity')
    return result


def reviewed(relative, deadline=None):
    if relative not in FILES:
        raise ValueError('unreviewed failure source')
    path = ROOT / relative
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 1024*1024:
        raise ValueError('invalid failure source')
    def remaining():
        value = 5 if deadline is None else min(5, deadline-time.monotonic())
        if value <= 0:
            raise ValueError('failure source deadline')
        return value
    env = {**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'}
    head = subprocess.run(['git', '-c', 'protocol.allow=never', 'rev-parse', 'HEAD'], cwd=ROOT,
                          capture_output=True, timeout=remaining(), env=env)
    if head.returncode or head.stdout.decode().strip() != identity()['sourceSHA']:
        raise ValueError('failure checkout differs')
    result = subprocess.run(['git', '-c', 'protocol.allow=never', 'show', 'HEAD:' + relative], cwd=ROOT,
                            capture_output=True, timeout=remaining(), env=env)
    data = path.read_bytes()
    if result.returncode or len(result.stdout) > 1024*1024 or result.stdout != data:
        raise ValueError('failure source differs')
    return data


def capture(error):
    """Inspect traceback locations only. Deliberately never call str(error)."""
    result = {'schema': 1, **identity(), 'status': 'unavailable', 'exceptionType':
              type(error).__name__ if type(error).__name__ in TYPES else 'Other', 'frames': []}
    try:
        deadline = time.monotonic()+15
        verified = {}
        def source(relative):
            if relative not in verified:
                verified[relative] = reviewed(relative, deadline)
            return verified[relative]
        source('tests/workload-identities/failure_evidence.py')
        frames, cursor, visited = [], error.__traceback__, 0
        while cursor is not None:
            visited += 1
            if visited > 128:
                raise ValueError('failure frame bound')
            path = Path(cursor.tb_frame.f_code.co_filename).absolute()
            if path.is_relative_to(ROOT):
                relative = path.relative_to(ROOT).as_posix()
                if relative in FILES:
                    data = source(relative)
                    line = cursor.tb_lineno
                    if not 1 <= line <= len(data.splitlines()):
                        raise ValueError('invalid failure line')
                    frames.append({'file': relative, 'line': line, 'sourceSHA256': hashlib.sha256(data).hexdigest()})
            cursor = cursor.tb_next
        if not frames or len(frames) > MAX_FRAMES:
            raise ValueError('failure frame bound')
        result.update(status='captured', frames=frames)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass  # Fixed unavailable state; no exception content escapes.
    return result


def write(directory, error):
    """First failure wins, including failures before the trial ID is assigned."""
    directory = Path(directory)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('invalid failure directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError('failure directory is not private')
    data = (json.dumps(capture(error), sort_keys=True) + '\n').encode()
    if len(data) > LIMIT:
        raise ValueError('failure capture bound')
    path = directory / NAME
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return  # Never replace the first failure or follow an existing symlink.
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)


def public(directory):
    """Revalidate the complete safe schema and every reviewed source/line."""
    deadline = time.monotonic()+15
    verified = {}
    def source(relative):
        if relative not in verified:
            verified[relative] = reviewed(relative, deadline)
        return verified[relative]
    source('tests/workload-identities/failure_evidence.py')
    path = Path(directory) / NAME
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('invalid failure capture')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError('invalid failure capture')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('failure capture bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate failure field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if (set(value) != {'schema', 'sourceSHA', 'runID', 'runAttempt', 'status', 'exceptionType', 'frames'}
            or type(value['schema']) is not int or value['schema'] != 1 or any(value[key] != item for key, item in identity().items())
            or value['status'] != 'captured' or value['exceptionType'] not in TYPES | {'Other'}
            or not isinstance(value['frames'], list) or not 1 <= len(value['frames']) <= MAX_FRAMES):
        raise ValueError('invalid failure capture schema')
    for frame in value['frames']:
        if set(frame) != {'file', 'line', 'sourceSHA256'} or frame['file'] not in FILES:
            raise ValueError('invalid failure frame')
        data = source(frame['file'])
        if (type(frame['line']) is not int or not 1 <= frame['line'] <= len(data.splitlines())
                or frame['sourceSHA256'] != hashlib.sha256(data).hexdigest()):
            raise ValueError('invalid failure source binding')
    return value
