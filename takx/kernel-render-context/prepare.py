#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in cached official source composition. Never compile, load or download."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import time

HERE = Path(__file__).resolve().parent
CAP = 4*1024**2
FLOOR = 2*1024**3
ORDER = ['official', 'baseline', 'texture', 'context', 'client_jni']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path, limit=2*1024**2):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError('bounded regular input required: '+str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('input changed type')
        data = stream.read(limit+1)
    if len(data) > limit:
        raise ValueError('input size bound')
    return data


def relative(name):
    path = PurePosixPath(name)
    unrelated = (path.parts[:3] != ('takkernel', 'engine', 'src') and
                 name != 'takkernel/port/src/jre/java/gov/tak/platform/commons/opengl/GLES20.java')
    if path.is_absolute() or '..' in path.parts or '\\' in name or unrelated:
        raise ValueError('unsafe or unrelated source path')
    return path.parts


def target(root, name):
    parts = relative(name)
    parent = root
    for part in parts[:-1]:
        parent /= part
        if parent.exists() or parent.is_symlink():
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise ValueError('source parent is not a real directory')
        else:
            break
    return root.joinpath(*parts)


def verify_stage(root, expected):
    for name, pin in expected.items():
        path = target(root, name)
        if pin is None:
            if path.exists() or path.is_symlink():
                raise ValueError('new source file must be absent: '+name)
        elif digest(regular(path)) != pin:
            raise ValueError('stage source image differs: '+name)


def selected_client_patch(raw, names):
    # This upstream profile uses traditional unified sections. Refuse format
    # churn rather than accidentally include a following unrelated diff header.
    if b'diff --git ' in raw:
        raise ValueError('client patch format changed; regenerate reviewed selection')
    matches = list(re.finditer(rb'(?m)^--- a/([^\r\n]+)\r?\n\+\+\+ b/([^\r\n]+)\r?\n', raw))
    selected, seen = [], set()
    for index, match in enumerate(matches):
        before, after = match.group(1).decode(), match.group(2).decode()
        if before != after:
            raise ValueError('client rename is outside contract')
        if after in names:
            if after in seen:
                raise ValueError('duplicate selected client section')
            seen.add(after)
            selected.append(raw[match.start():matches[index+1].start() if index+1 < len(matches) else len(raw)])
    if seen != set(names):
        raise ValueError('selected client JNI section missing')
    return b''.join(selected)


def load_contract():
    lock = json.loads(regular(HERE/'inputs.lock.json'))
    scope = json.loads(regular(HERE/'source-scope.json'))
    patch = regular(HERE/'render-context-control.patch')
    if (lock['official_revision'] != '9f6893dd657feacc35ec5de03dad721c2e44170e' or
        lock['actual_kernel_version'] != '8.30.5' or lock['stage_order'] != ORDER):
        raise ValueError('source identity or stage order differs')
    if digest(patch) != lock['context_patch_sha256'] or digest(regular(HERE/'source-scope.json')) != lock['context_scope_sha256']:
        raise ValueError('owned source patch/scope differs')
    if scope['patch_sha256'] != lock['context_patch_sha256']:
        raise ValueError('source scope patch differs')
    required_client = {
        'takkernel/engine/src/main/jni/interop/feature/Interop.cpp',
        'takkernel/engine/src/main/jni/jscenelayer.cpp',
        'takkernel/engine/src/main/java/com/atakmap/map/layer/feature/FeatureLayer3.java',
    }
    if set(lock['client_jni']['files']) != required_client:
        raise ValueError('paired client JNI and Java sources differ')
    for name, images in lock['client_jni']['files'].items():
        if (lock['stages']['context'].get(name) != images['before'] or
                lock['stages']['client_jni'].get(name) != images['after']):
            raise ValueError('paired client JNI and Java stage images differ')
    names = set(lock['stages']['official'])
    for stage in ORDER:
        if set(lock['stages'][stage]) != names:
            raise ValueError('stage membership differs')
        for name, pin in lock['stages'][stage].items():
            relative(name)
            if pin is not None and not re.fullmatch('[0-9a-f]{64}', pin):
                raise ValueError('invalid stage digest')
    return lock, patch


def profile_inputs(lock, baseline, texture, client):
    files = {}
    def read(root, name):
        path = root/name
        data = regular(path)
        files[str(path)] = digest(data)
        return data
    base = json.loads(read(baseline, 'inputs.lock.json'))
    if base['revision'] != lock['official_revision'] or base['kernel_version'] != '8.30.5':
        raise ValueError('baseline identity differs')
    expected = lock['baseline_patches']
    if set(base['patches']) != set(expected):
        raise ValueError('baseline patch set changed')
    patches = []
    for name, entry in expected.items():
        if base['patches'][name] != {k: v for k, v in entry.items() if k != 'patch_sha256'}:
            raise ValueError('baseline patch target/images differ')
        data = read(baseline/'patches', name)
        if digest(data) != entry['patch_sha256']:
            raise ValueError('baseline patch bytes differ')
        patches.append(('baseline-'+name, data))
    tex = json.loads(read(texture, 'source.lock.json'))
    tex_patch = read(texture, 'texture-fill.patch')
    if (tex['source_commit'] != lock['official_revision'] or tex['actual_kernel_version'] != '8.30.5' or
        tex['files'] != lock['texture']['files'] or digest(tex_patch) != lock['texture']['patch_sha256'] or
        tex['patch_sha256'] != lock['texture']['patch_sha256']):
        raise ValueError('frozen Texture source contract differs')
    cli = json.loads(read(client, 'inputs.lock.json'))
    cli_patch = read(client, 'client-contracts.patch')
    if cli['official_revision'] != lock['official_revision'] or cli['actual_kernel_version'] != '8.30.5':
        raise ValueError('client JNI identity differs')
    if digest(cli_patch) != cli['patch_sha256']:
        raise ValueError('client profile full patch differs from its own lock')
    chosen = lock['client_jni']['files']
    if {name: cli['files'].get(name) for name in chosen} != chosen:
        raise ValueError('selected client JNI source images differ')
    selected = selected_client_patch(cli_patch, chosen)
    if digest(selected) != lock['client_jni']['selected_patch_sha256']:
        raise ValueError('selected client JNI patch differs')
    return files, patches, tex_patch, selected


class Runner:
    def __init__(self, output):
        self.output = output
        self.deadline = time.monotonic()+120
        self.records = []

    def check(self, reserve=131072):
        if time.monotonic() >= self.deadline:
            raise ValueError('source preparation aggregate deadline')
        used = sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file())
        if used+reserve > CAP or shutil.disk_usage(self.output).free < FLOOR+reserve:
            raise ValueError('source preparation output cap or free floor')

    def run(self, argv, limit=2*1024**2):
        # Tool streams are bounded in memory; reserve disk only when their
        # exact source/receipt bytes are about to be written.
        self.check()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'GIT_'))}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0',
                   GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_PAGER='cat', LC_ALL='C.UTF-8')
        def limits():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_FSIZE, (2*1024**2, 2*1024**2))
        started = time.monotonic()
        proc = subprocess.Popen(list(map(str, argv)), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, preexec_fn=limits)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, 0)
        selector.register(proc.stderr, selectors.EVENT_READ, 1)
        buffers = [bytearray(), bytearray()]
        end = min(self.deadline, started+20)
        try:
            while selector.get_map():
                remaining = end-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('source tool deadline')
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fileobj.fileno(), 32768)
                    if not data:
                        selector.unregister(key.fileobj)
                    elif len(buffers[key.data])+len(data) > (limit if key.data == 0 else 65536):
                        raise ValueError('bounded source tool stream exceeded')
                    else:
                        buffers[key.data].extend(data)
            remaining = end-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('source tool deadline')
            code = proc.wait(timeout=remaining)
        finally:
            selector.close()
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            proc.stdout.close()
            proc.stderr.close()
        self.records.append({'argv': list(map(str, argv)), 'returncode': code,
                             'stdout_sha256': digest(buffers[0]), 'stdout_bytes': len(buffers[0]),
                             'stderr_sha256': digest(buffers[1]), 'stderr': buffers[1].decode(errors='replace')})
        if code:
            raise ValueError('cached source or exact patch command failed')
        return bytes(buffers[0])


def prepare(args):
    lock, context_patch = load_contract()
    inputs, baseline_patches, texture_patch, client_patch = profile_inputs(
        lock, args.baseline_profile.resolve(), args.texture_profile.resolve(), args.client_profile.resolve())
    for name in ('prepare.py', 'inputs.lock.json', 'source-scope.json', 'render-context-control.patch'):
        inputs[str(HERE/name)] = digest(regular(HERE/name))
    source, output = args.source.resolve(), args.output.resolve()
    protected = [source, HERE.parent.parent, args.baseline_profile.resolve(), args.texture_profile.resolve(), args.client_profile.resolve()]
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('fresh output must be disjoint from all input roots')
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('new output under an existing parent is required')
    if shutil.disk_usage(output.parent).free < FLOOR+CAP:
        raise ValueError('2GiB floor plus source output reservation required')
    output.mkdir(mode=0o700)
    runner = Runner(output)
    projection, patches = output/'source', output/'patches'
    projection.mkdir()
    patches.mkdir()
    tools = {}
    try:
        for kind in ('git', 'patch'):
            tool = Path(shutil.which(getattr(args, kind)) or getattr(args, kind)).resolve()
            tools[kind] = {'path': str(tool), 'sha256': digest(regular(tool, 32*1024**2))}
        for name, pin in lock['stages']['official'].items():
            if pin is None:
                continue
            data = runner.run([tools['git']['path'], '--no-lazy-fetch', '--no-replace-objects', '-C', source,
                               'show', lock['official_revision']+':'+name])
            if digest(data) != pin:
                raise ValueError('official blob bytes differ: '+name)
            path = target(projection, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            runner.check(len(data))
            path.write_bytes(data)
        verify_stage(projection, lock['stages']['official'])
        operations = [('baseline', baseline_patches), ('texture', [('texture.patch', texture_patch)]),
                      ('context', [('context.patch', context_patch)]), ('client_jni', [('client-jni.patch', client_patch)])]
        for stage, entries in operations:
            for name, data in entries:
                patch = patches/name
                runner.check(len(data))
                patch.write_bytes(data)
                runner.run([tools['patch']['path'], '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p1',
                            '-d', projection, '-i', patch], limit=65536)
            verify_stage(projection, lock['stages'][stage])
        actual = {str(p.relative_to(projection)) for p in projection.rglob('*') if p.is_file()}
        if actual != {n for n, h in lock['stages']['client_jni'].items() if h is not None}:
            raise ValueError('final sparse source membership differs')
        for name, pin in inputs.items():
            if digest(regular(Path(name))) != pin:
                raise ValueError('consumed profile input changed')
        for item in tools.values():
            if digest(regular(Path(item['path']), 32*1024**2)) != item['sha256']:
                raise ValueError('source tool changed')
        receipt = {'scope': 'source preparation only; no compiler, library load, JVM or download',
                   'official_revision': lock['official_revision'], 'actual_kernel_version': '8.30.5',
                   'stage_order': ORDER, 'stage_images': lock['stages'], 'inputs': inputs, 'tools': tools,
                   'commands': runner.records, 'native_builder_integration': False,
                   'native_build_or_execution': False, 'gpu_qualified': False, 'full_sdk_accepted': False}
        data = (json.dumps(receipt, indent=2, sort_keys=True)+'\n').encode()
        runner.check(len(data))
        (output/'prepared.json').write_bytes(data)
        runner.check(0)
    except BaseException as error:
        (output/'first-failure.json').write_text(json.dumps({'error': repr(error), 'source_only': True})+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['verify', 'prepare'], default='verify')
    for name in ['source', 'baseline-profile', 'texture-profile', 'client-profile', 'output']:
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--git', default='git')
    parser.add_argument('--patch', default='patch')
    args = parser.parse_args()
    if args.phase == 'verify':
        if any(getattr(args, n) for n in ['source', 'baseline_profile', 'texture_profile', 'client_profile', 'output']):
            parser.error('input/output paths require explicit --phase prepare')
        load_contract()
    else:
        if not all(getattr(args, n) for n in ['source', 'baseline_profile', 'texture_profile', 'client_profile', 'output']):
            parser.error('prepare needs cached source, three profile paths and fresh output')
        prepare(args)


if __name__ == '__main__':
    main()
