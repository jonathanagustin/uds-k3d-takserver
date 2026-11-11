# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exact public Gradle resource projection; no Android resource-table semantics."""
import hashlib
import re
from pathlib import PurePosixPath

CATALOG = 'META-INF/uds-desktop-resources.properties'
ROOTS = ('takkernel/engine/src/main/res/', 'takkernel/engine/src/main/assets/',
         'takkernel/shared/src/main/res/', 'takkernel/shared/src/main/assets/')

def destination(source):
    if not any(source.startswith(root) for root in ROOTS):
        raise ValueError('resource outside reviewed production roots')
    path = PurePosixPath(source)
    if str(path) != source or '..' in path.parts or '\\' in source:
        raise ValueError('unsafe resource path')
    tail = '/'.join(path.parts[5:])
    if path.parts[4] == 'assets':
        return 'assets/' + tail, 'asset'
    # Gradle strips the final extension only when its dot is not initial.
    name = path.name
    if name.rfind('.') > 0:
        name = name[:name.rfind('.')]
    return 'resources/' + str(PurePosixPath(tail).with_name(name)), path.parts[5]

def merge(*groups):
    result = {}
    for group in groups:
        if result.keys() & group.keys():
            raise ValueError('duplicate JAR destination')
        result.update(group)
    return result

def collect(lock, tree, read, payload=None):
    """tree is the exact Git production-root file inventory; read returns blob bytes."""
    expected = {item['source']: item for item in lock['files']}
    if len(expected) != len(lock['files']) or set(tree) != set(expected):
        raise ValueError('complete resource source inventory differs')
    entries, catalog = {}, {}
    owner = lock['namespace']
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', owner):
        raise ValueError('invalid resource namespace')
    for source, item in expected.items():
        dest, kind = destination(source)
        if item['destination'] != dest or item['kind'] != kind or tree[source] != (item['mode'], item['blob'], item['bytes']) or item['mode'] != '100644':
            raise ValueError('resource mapping or Git identity differs')
        data = read(source)
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('resource bytes differ')
        materialized = item.get('lfs_payload')
        if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
            if not materialized or not re.fullmatch(r'[0-9a-f]{64}', materialized['sha256']) or not isinstance(materialized['bytes'], int) or materialized['bytes'] <= 0:
                raise ValueError('unreviewed Git LFS resource pointer')
            canonical = ('version https://git-lfs.github.com/spec/v1\noid sha256:'+materialized['sha256']+'\nsize '+str(materialized['bytes'])+'\n').encode()
            if data != canonical:
                raise ValueError('Git LFS pointer identity differs')
            if payload is None:
                raise ValueError('declared Git LFS payload store required')
            data = payload(materialized['sha256'])
            if len(data) != materialized['bytes'] or hashlib.sha256(data).hexdigest() != materialized['sha256']:
                raise ValueError('Git LFS payload bytes differ')
        elif materialized:
            raise ValueError('locked Git LFS pointer is absent')
        entries = merge(entries, {dest: data})
        if kind in ('raw', 'drawable'):
            if kind == 'drawable' and PurePosixPath(source).suffix != '.png':
                raise ValueError('unsupported drawable binary format')
            name = PurePosixPath(dest).name
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                raise ValueError('invalid catalog resource name')
            key = owner + '/' + kind + '/' + name
            if key in catalog:
                raise ValueError('duplicate catalog identity')
            catalog[key] = dest
        elif kind not in ('values', 'asset'):
            raise ValueError('unsupported resource type')
    entries = merge(entries, {CATALOG: ''.join(k+'='+v+'\n' for k,v in sorted(catalog.items())).encode()})
    return entries
