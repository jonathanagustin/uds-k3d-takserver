#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Verify or prepare three pinned font sources; never build or install a JDK."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PREFIX = 'src/java.desktop/share/native/libfontmanager/'
FILES = {PREFIX + name for name in ('HBShaper.c', 'freetypeScaler.c', 'hb-jdk-font.cc')}
LIMIT = 512 * 1024


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
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        data = source.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'input size bound')
    return data


def contract():
    lock = json.loads(regular(HERE / 'inputs.lock.json'))
    patch = regular(HERE / 'font-exception-checks.patch')
    require(type(lock['schema']) is int and lock['schema'] == 1 and lock['official_revision'] ==
            'e8adc958475b92b9f251145c6ce20532be16d806' and
            lock['official_tag'] == 'jdk-17.0.21+9', 'source identity differs')
    require(set(lock['files']) == FILES, 'source membership differs')
    for images in lock['files'].values():
        require(set(images) == {'before', 'after'}, 'source image schema differs')
        for value in images.values():
            require(isinstance(value, str) and len(value) == 64 and
                    all(c in '0123456789abcdef' for c in value), 'source image digest differs')
    require(all(lock[key] is False for key in ('stock_source_binary_equivalence',
            'native_builder_integration', 'runtime_accepted', 'full_sdk_accepted')),
            'unqualified source profile cannot grant acceptance')
    require(lock['patch_license'] == 'GPL-2.0-only WITH Classpath-exception-2.0' and
            digest(patch) == lock['patch_sha256'], 'patch identity differs')
    for marker in (b'--- a/', b'+++ b/'):
        names = re.findall(b'^' + re.escape(marker) + b'([^\r\n]+)', patch, re.MULTILINE)
        require(len(names) == 3 and {name.decode() for name in names} == FILES, 'patch scope differs')
    return lock, patch


def prepare(source, output, patch_tool='patch'):
    lock, patch = contract()
    source = Path(source).absolute()
    output = Path(output).absolute()
    require(not any(p.is_symlink() for p in (source, *source.parents, output, *output.parents)),
            'symlink root refused')
    for root in (source, HERE.parents[2]):
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output),
                'fresh output must be disjoint from all source inputs')
    require(output.parent.is_dir() and not output.exists(), 'fresh output required')
    tool = Path(shutil.which(patch_tool) or patch_tool).resolve(strict=True)
    tool_hash = hashlib.sha256(tool.read_bytes()).hexdigest()
    # Authenticate all original inputs before creating the output.
    inputs = {name: regular(source / name) for name in FILES}
    for name, data in inputs.items():
        require(digest(data) == lock['files'][name]['before'], 'official source bytes differ')
    output.mkdir(mode=0o700)
    try:
        for name, data in inputs.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with tempfile.TemporaryFile() as stream:
            stream.write(patch)
            stream.seek(0)
            env = {key: value for key, value in os.environ.items()
                   if key not in ('BASH_ENV', 'ENV') and not key.startswith(('LD_', 'DYLD_'))}
            env['LC_ALL'] = 'C'
            result = subprocess.run([str(tool), '--batch', '--fuzz=0', '--no-backup-if-mismatch',
                                     '-p1', '-d', str(output)], stdin=stream,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=20, env=env, check=False)
        require(result.returncode == 0 and len(result.stdout) + len(result.stderr) <= LIMIT,
                'exact source patch failed')
        actual = {str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()}
        require(actual == FILES, 'prepared source membership differs')
        for name in FILES:
            require(digest(regular(output / name)) == lock['files'][name]['after'], 'prepared source bytes differ')
            require(regular(source / name) == inputs[name], 'official input changed')
        require(hashlib.sha256(tool.read_bytes()).hexdigest() == tool_hash, 'patch tool changed')
        require(contract() == (lock, patch), 'source contract changed')
        receipt = {'schema': 1, 'scope': lock['scope'], 'official_revision': lock['official_revision'],
                   'files': lock['files'], 'patch_sha256': digest(patch), 'patch_tool_sha256': tool_hash,
                   'native_build_or_execution': False, 'runtime_accepted': False, 'full_sdk_accepted': False}
        (output / 'prepared.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    except BaseException:
        (output / 'first-failure.json').write_text('{"runtime_accepted":false,"source_prepare_failed":true}\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'prepare'), default='verify')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.phase == 'verify':
        require(args.source is None and args.output is None, 'paths require explicit prepare phase')
        contract()
    else:
        require(args.source is not None and args.output is not None, 'prepare requires source and output')
        prepare(args.source, args.output)


if __name__ == '__main__':
    main()
