#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Verify or prepare one pinned elevation source; no compiler or native launch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
FILE = 'takkernel/engine/src/main/jni/interop/elevation/ManagedElevationSource.cpp'
OLD = b'ElevationSource_QueryParameters_class.ctor = env->GetMethodID(ElevationSource_class.id, "<init>", "()V");'
NEW = b'ElevationSource_QueryParameters_class.ctor = env->GetMethodID(ElevationSource_QueryParameters_class.id, "<init>", "()V");'
FLAGS = ('native_builder_integration', 'strict_elevation_accepted', 'full_sdk_accepted', 'full_client_accepted')
LIMIT = 256 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink input refused')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= LIMIT, 'bounded regular input required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        data = source.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'input size bound')
    return data


def contract():
    lock = json.loads(regular(HERE / 'inputs.lock.json'))
    patch = regular(HERE / 'elevation-query-constructor.patch')
    require(type(lock['schema']) is int and lock['schema'] == 1 and
            lock['profile'] == 'public-elevation-query-constructor-v1' and
            lock['official_revision'] == '9f6893dd657feacc35ec5de03dad721c2e44170e' and
            lock['actual_kernel_version'] == '8.30.5' and lock['file'] == FILE, 'source identity differs')
    require(all(lock[key] is False for key in FLAGS), 'source preparation cannot grant acceptance')
    require(all(isinstance(lock[key], str) and re.fullmatch('[a-f0-9]{64}', lock[key])
                for key in ('before', 'after', 'patch_sha256')), 'source digest differs')
    require(digest(patch) == lock['patch_sha256'], 'patch bytes differ')
    for marker in (b'--- a/', b'+++ b/'):
        require(re.findall(b'^' + re.escape(marker) + b'([^\r\n]+)', patch, re.MULTILINE) == [FILE.encode()],
                'patch source membership differs')
    deleted = [line[1:].strip() for line in patch.splitlines() if line.startswith(b'-') and not line.startswith(b'---')]
    added = [line[1:].strip() for line in patch.splitlines() if line.startswith(b'+') and not line.startswith(b'+++')]
    require(deleted == [OLD] and added == [NEW], 'constructor correction differs')
    return lock, patch


def prepare(source, output):
    lock, patch = contract()
    source, output = Path(source).absolute(), Path(output).absolute()
    require(not any(p.is_symlink() for p in (source, *source.parents, output, *output.parents)), 'symlink root refused')
    for root in (source, HERE.parents[1]):
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output), 'output overlaps inputs')
    require(output.parent.is_dir() and not output.exists(), 'fresh output required')
    producer = regular(HERE / 'prepare.py')
    original = regular(source / FILE)
    require(digest(original) == lock['before'] and original.count(OLD) == 1, 'official source bytes differ')
    transformed = original.replace(OLD, NEW)
    require(digest(transformed) == lock['after'], 'corrected source bytes differ')
    output.mkdir(mode=0o700)
    try:
        target = output / FILE
        target.parent.mkdir(parents=True)
        target.write_bytes(transformed)
        require(regular(target) == transformed and regular(source / FILE) == original, 'prepared or original source changed')
        require(contract() == (lock, patch) and regular(HERE / 'prepare.py') == producer, 'source contract changed')
        receipt = {'schema': 1, 'type': 'public-elevation-constructor-source', 'scope': lock['scope'],
                   'official_revision': lock['official_revision'], 'file': FILE,
                   'before': digest(original), 'after': digest(transformed), 'patch_sha256': digest(patch),
                   'producer_sha256': digest(producer),
                   'native_build_or_execution': False, **{key: False for key in FLAGS}}
        (output / 'prepared.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    except BaseException:
        (output / 'first-failure.json').write_text('{"source_prepare_failed":true,"strict_elevation_accepted":false}\n')
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'prepare'), default='verify')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.phase == 'verify':
        require(args.source is None and args.output is None, 'paths require explicit prepare phase')
        contract()
    else:
        require(args.source is not None and args.output is not None, 'source and fresh output required')
        prepare(args.source, args.output)


if __name__ == '__main__':
    main()
