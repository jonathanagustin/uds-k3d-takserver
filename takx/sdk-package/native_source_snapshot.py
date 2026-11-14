# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bind a reviewed nonexecuted source bundle to an explicitly pinned native receipt."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


def require(value, message):
    if not value:
        raise ValueError(message)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def regular(path, limit, readonly=False):
    path = Path(path).absolute()
    require(path.resolve() == path and path.is_file() and not path.is_symlink(), 'canonical regular snapshot input required')
    before=path.lstat()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino)==(before.st_dev,before.st_ino), 'snapshot input identity changed')
        require(info.st_size <= limit and (not readonly or not info.st_mode & 0o333), 'bounded nonexecutable read-only snapshot required')
        value=stream.read(limit+1);after=os.fstat(stream.fileno())
    current=path.lstat()
    identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns)
    require(len(value)<=limit and identity(info)==identity(after)==identity(current),'snapshot input bound or identity changed')
    return value


def verify(snapshot, receipt, expected_receipt_sha256, known):
    # The caller's expected receipt hash is checked before JSON or source reads.
    require(isinstance(expected_receipt_sha256, str) and re.fullmatch('[a-f0-9]{64}', expected_receipt_sha256), 'explicit native receipt SHA required')
    receipt_bytes = regular(receipt, 32 * 1024**2)
    require(digest_bytes(receipt_bytes) == expected_receipt_sha256, 'explicit native receipt SHA differs')
    root = Path(snapshot).absolute()
    require(root.is_dir() and root.resolve() == root and not root.is_symlink() and not root.stat().st_mode & 0o222, 'frozen source bundle directory required')
    manifest_bytes = regular(root / 'manifest.json', 128 * 1024, readonly=True)
    manifest_sha = digest_bytes(manifest_bytes)
    require(manifest_sha in known, 'source bundle is not consumer-reviewed')
    pin = known[manifest_sha]
    manifest = json.loads(manifest_bytes)
    require(type(manifest['schema']) is int and manifest['schema'] == 1 and manifest['profile'] == pin['profile'] and
            manifest['sourceCount'] == pin['source_count'] and manifest['gitSourceCommit'] == pin['git_source_commit'] and
            manifest['nativeRecipeSHA256'] == pin['native_recipe_sha256'], 'reviewed source manifest contract differs')
    record = json.loads(receipt_bytes)
    recipe = record['recipe']
    recipe_sha = digest_bytes(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode())
    require(recipe_sha == pin['native_recipe_sha256'] and len(recipe) == pin['source_count'] == len(manifest['files']), 'original native recipe differs from reviewed source bundle')
    recipe_file=manifest['recipeFile']
    require(recipe_file['path']=='recipe.json','fixed recipe member required')
    recipe_bytes=regular(root/'recipe.json',128*1024,readonly=True)
    require(len(recipe_bytes)==recipe_file['bytes'] and digest_bytes(recipe_bytes)==recipe_file['sha256'] and
            json.loads(recipe_bytes)==recipe,'frozen recipe JSON differs')
    actual, members = {}, {'manifest.json','recipe.json'}
    for row in manifest['files']:
        relative = PurePosixPath(row['snapshotPath'])
        require(not relative.is_absolute() and '..' not in relative.parts and str(relative) == row['snapshotPath'] and
                relative.parts[:2] == ('source', 'takx') and '\\' not in str(relative), 'source bundle path escape')
        require(row['snapshotPath'] not in members and row['receiptRecipePath'] not in actual, 'duplicate snapshot member')
        body = regular(root / row['snapshotPath'], 2 * 1024**2, readonly=True)
        require(len(body) == row['bytes'] and digest_bytes(body) == row['sha256'], 'exact historical source body differs')
        actual[row['receiptRecipePath']] = row['sha256'];members.add(row['snapshotPath'])
    require(actual == recipe, 'entire original source closure differs')
    expected_dirs={str(parent) for name in members for parent in PurePosixPath(name).parents if str(parent)!='.'}
    observed,observed_dirs=set(),set()
    for index,path in enumerate(root.rglob('*')):
        require(index<len(members)+len(expected_dirs),'source bundle membership bound')
        name=path.relative_to(root).as_posix();info=path.lstat()
        require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'source bundle link or special member')
        if stat.S_ISDIR(info.st_mode):
            require(name in expected_dirs and not info.st_mode & 0o222,'source bundle directory differs or is writable')
            observed_dirs.add(name)
        else:
            require(name in members,'unexpected source bundle member');observed.add(name)
    require(observed == members and observed_dirs==expected_dirs, 'unexpected source bundle membership')
    return {'manifest_sha256': manifest_sha, 'native_receipt_sha256': expected_receipt_sha256,
            'native_recipe_sha256': recipe_sha, 'source_count': len(actual), 'historical_code_executed': False}
