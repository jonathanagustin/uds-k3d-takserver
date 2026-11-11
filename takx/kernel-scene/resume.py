#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit audited continuation of a stopped producer; never a fresh-build claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scene_resume_build', HERE / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
# This single stopped producer was reviewed and snapshotted before mutation.
SNAPSHOT_SHA = '6b260ffcd8d83f35f940c1c13d8b9a353530967f52fc4ef01f81660bf7287f3c'
ORIGINAL_RECIPE = '98f752c6c41385b8cb4ebe82a0acadfc72d730d7b652db024f87fa9c3ad7e302'
ORIGINAL_LOCK = 'cab2e6e75d2e26f7e2ac7eced4eb50396b6d02db63e205348a0a178097d73db4'


def verify_snapshot(original, snapshot, manifest):
    if manifest.is_symlink() or build.native.digest(manifest) != SNAPSHOT_SHA:
        raise ValueError('unreviewed timeout snapshot manifest')
    expected = json.loads(manifest.read_text())
    if build.inventory(snapshot) != expected or build.inventory(original) != expected:
        raise ValueError('changed or unknown resume input')
    failed = json.loads((original / 'failed.json').read_text())
    if (failed['stage'], failed['last_command'], failed['kernel_scene_acceptance']) != ('gdal', 'gdal-build', False):
        raise ValueError('not the stopped GDAL producer')
    if failed['recipe']['build.py'] != ORIGINAL_RECIPE or failed['recipe']['inputs.lock.json'] != ORIGINAL_LOCK:
        raise ValueError('original producer identity differs')
    return expected, failed['recipe']


def relocatable(path):
    """Reject incomplete ELF64/x86-64 objects, including truncated section data."""
    with path.open('rb') as stream:
        header = stream.read(64)
        size = path.stat().st_size
        if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01':
            return False
        fields = struct.unpack('<16sHHIQQQIHHHHHH', header)
        _, kind, machine, version, _, _, offset, _, ehsize, _, _, entsize, count, strings = fields
        if (kind, machine, version, ehsize, entsize) != (1, 62, 1, 64, 64) or not count or strings >= count:
            return False
        if offset + count * entsize > size:
            return False
        stream.seek(offset)
        for _ in range(count):
            section = struct.unpack('<IIQQQQIIQQ', stream.read(64))
            if section[1] != 8 and section[4] + section[5] > size:  # SHT_NOBITS has no file payload.
                return False
    return True


def object_audit(root, log):
    expected = build.inventory(root)
    targets = re.findall(r' -c -o ([\w./-]+\.lo) ', log)
    if not targets:
        raise ValueError('cannot identify last potentially interrupted compile')
    last = Path(targets[-1]).stem
    remove = {}
    for name, record in expected.items():
        path = root / name
        if path.suffix == '.o' and (not relocatable(path) or path.stem == last):
            remove[name] = {'reason': 'interrupted-last-compile' if path.stem == last else 'invalid-relocatable', **record}
        if path.suffix == '.lo' and path.stem == last:
            remove[name] = {'reason': 'interrupted-libtool-target', **record}
    return expected, remove


def dependency_bindings(original, tools):
    names = ['configuration.json', 'gdal-build/GDALmake.opt', 'gdal-build/port/cpl_config.h',
             'sources.json', 'minizip/libminizip.a', 'minizip/libminizip-pic.so',
             'minizip/minizip-probe', 'minizip-positive-controls.log', 'minizip-strict-link.log']
    if (original / 'minizip-positive-controls.log').read_bytes() != b'real_minizip_binary_crc_correct_and_wrong_password_controls=true\n':
        raise ValueError('actual minizip controls missing')
    return {'files': {name: build.native.digest(original / name) for name in names}, 'tools': tools}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'snapshot', 'manifest', 'producer', 'output', 'source', 'proj_proof', 'assimp_proof'):
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    output = build.validate_output(args.output, [args.original, args.snapshot, args.manifest, args.producer,
        args.source, args.proj_proof, args.assimp_proof, HERE])
    expected, old_recipe = verify_snapshot(args.original, args.snapshot, args.manifest)
    configuration = json.loads((args.original / 'configuration.json').read_text())
    if (configuration['args'][0] != str(args.original.resolve() / 'gdal-build/configure') or
            '--prefix=' + str(args.original.resolve() / 'gdal-install') not in configuration['args']):
        raise ValueError('absolute producer paths differ; relocation is not supported')
    for name, sha in old_recipe.items():
        path = args.producer / name.replace('../', 'parent/')
        if path.is_symlink() or build.native.digest(path) != sha:
            raise ValueError('original producer bytes unavailable')
    deps = {family: build.verify_dependency(root, family) for family, root in (
        ('proj', args.proj_proof), ('assimp', args.assimp_proof))}
    # Bind the existing compiler/binutils/make and configure-driving CMake to
    # already-verified leaf producer receipts, not executable names from PATH.
    tools = {}
    for proof in (args.proj_proof, args.assimp_proof):
        for name, item in json.loads((proof / 'complete.json').read_text())['tools'].items():
            tools[item['path']] = item['sha256']
    for path, sha in tools.items():
        if build.native.digest(Path(path)) != sha:
            raise ValueError('resume tool changed')
    bound = dependency_bindings(args.original, tools)
    obj_inventory, remove = object_audit(args.original / 'gdal-build', (args.original / 'gdal-build.log').read_text())
    output.mkdir()
    initial = build.recipe()
    lineage = {'fresh_build': False, 'original_recipe': old_recipe, 'resumed_recipe': initial,
        'timeout_snapshot_manifest_sha256': SNAPSHOT_SHA, 'dependency_bindings_before': bound,
        'produced_object_inventory': {p:v for p,v in obj_inventory.items() if p.endswith('.o')},
        'removed_owned_outputs': remove, 'original_gdal_chunk_seconds': 1200, 'additional_chunk_seconds': 1200,
        'total_gdal_command_bound_seconds': 2400}
    (output / 'lineage.json').write_text(json.dumps(lineage, sort_keys=True) + '\n')
    # The entire old state was compared before any removal. Never remove source,
    # configuration, library, or an output outside the exact audited object list.
    for name in remove:
        (args.original / 'gdal-build' / name).unlink()
    cc, cxx = Path('/usr/bin/gcc').resolve(), Path('/usr/bin/g++').resolve()
    env = build.assimp.environment(str(cc), str(cxx))
    for key in list(env):
        if key.startswith(('PROJ_', 'GDAL_', 'PKG_CONFIG', 'BASH_FUNC_')) or key in (
            'MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS', 'MAKEFILES', 'CONFIG_SITE', 'CONFIG_SHELL',
            'CPATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC', CXXFLAGS='-O2 -fPIC', CONFIG_SITE='/dev/null',
        PKG_CONFIG_LIBDIR=str(output / 'no-pkgconfig'), PKG_CONFIG_PATH='', CC=str(cc), CXX=str(cxx))
    stage, deadline, commands = 'resumed-gdal', time.monotonic() + 1200, []

    def run(command, name, timeout=60, capture=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('continuation stage deadline exhausted')
        commands.append({'stage': stage, 'name': name, 'command': list(map(str, command))})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        result = build.native.run(list(map(str, command)), output, name, min(remaining, timeout), env, capture)
        if sum(p.stat().st_size for root in (output,args.original) for p in root.rglob('*')
               if p.is_file() and not p.is_symlink()) > 4 * 1024**3:
            raise ValueError('continuation output bound exceeded')
        return result

    try:
        run(['/usr/bin/make', '-C', args.original / 'gdal-build', '-j1'], 'gdal-resumed-build', 1200)
        run(['/usr/bin/make', '-C', args.original / 'gdal-build', '-j1', 'install'], 'gdal-resumed-install', 180)
        if dependency_bindings(args.original, tools) != bound:
            raise ValueError('resumed dependency inputs changed')
        for family, proof in [('proj',args.proj_proof),('assimp',args.assimp_proof)]:
            if build.verify_dependency(proof,family) != deps[family]:
                raise ValueError('dependency proof changed')
        for path, sha in tools.items():
            if build.native.digest(Path(path)) != sha:
                raise ValueError('tool changed during continuation')
        receipt = build.producer.emit(args.original,output,initial,
            json.loads((args.original/'sources.json').read_text()),tools,lineage,False)
        stage, deadline = 'kernel-scene', time.monotonic() + 1200
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        frozen = output / 'source'
        frozen.mkdir()
        # Dependency source stays in the preserved original prefix, while new
        # Kernel inputs and products belong solely to this resumed invocation.
        source_post = json.loads((args.original / 'sources.json').read_text())
        build.kernel_stage(args, output, run, lock, initial, deps, frozen, source_post,
            args.original / 'source/libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip',
            args.assimp_proof / 'zlib-install', args.original / 'minizip/libminizip.a',
            args.original / 'gdal-install', cxx, env, receipt, args.original / 'source')
        # Validate both unchanged dependency source inventories after Kernel use.
        actual = build.inventory(args.original / 'source')
        if actual != source_post or build.recipe() != initial:
            raise ValueError('source or recipe changed during resumed integration')
        result = json.loads((output / 'complete.json').read_text())
        result['fresh_build'] = False
        result['producer_lineage_sha256'] = build.native.digest(output / 'lineage.json')
        (output / 'complete.json').write_text(json.dumps(result, indent=2) + '\n')
    except Exception:
        # A later acceptance check must not leave a premature success receipt.
        if (output / 'complete.json').exists():
            (output / 'complete.json').unlink()
        (output / 'failed.json').write_text(json.dumps({'stage': stage, 'kernel_scene_acceptance': False,
            'last_command': commands[-1]['name'] if commands else None, 'resumed_recipe': initial,
            'original_recipe': old_recipe}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
