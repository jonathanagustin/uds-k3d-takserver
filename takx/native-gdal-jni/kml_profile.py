#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a verified private GDAL KML configuration; never configure/build/run."""
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            result.update(chunk)
    return result.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def checked(path, expected):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            'regular canonical dependency required')
    require(re.fullmatch('[0-9a-f]{64}', expected) and digest(path) == expected, 'dependency SHA differs')
    require(not any(c.isspace() or c in "'\"$;`" for c in str(path)), 'pkg-config path requires literal safe characters')
    return path


def verify_inventory(root, expected):
    require(root.is_dir() and not root.is_symlink(), 'complete provider directory required')
    actual = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'dependency symlink rejected')
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = digest(path)
    normalized = {name: value['sha256'] if isinstance(value, dict) else value for name, value in expected.items()}
    require(actual == normalized, 'complete qualified dependency inventory differs')
    for name, value in expected.items():
        if isinstance(value, dict):
            require((root / name).stat().st_size == value['bytes'], 'qualified provider size differs')


def prepare(kml_root, receipt_sha256, bindings, output, base_configure):
    """Bindings explicitly identify archives/receipts; no host package discovery."""
    kml_root, output = Path(kml_root).resolve(), Path(output).absolute()
    receipt = checked(kml_root / 'complete.json', receipt_sha256)
    proof = json.loads(receipt.read_text())
    require(proof.get('profile') == 'public-libkml-native' and proof.get('version') == '1.3.0'
            and proof.get('expat_version') == '2.10.0' and proof.get('strict_whole_archive_pic') is True
            and proof.get('dom_kmz_uri_controls') is True and proof.get('private_static_expat_dynsym_verified') is True,
            'genuine qualified LibKML/Expat producer required')
    verify_inventory(kml_root / 'install', proof['installed'])
    verify_inventory(kml_root / 'expat-install', proof['expat_installed'])
    require(set(bindings) == {'minizip', 'uriparser', 'zlib', 'zlibReceipt', 'boostRoot'}, 'exact provider bindings required')
    archives = {name: checked(bindings[name]['path'], bindings[name]['sha256'])
                for name in ('minizip', 'uriparser', 'zlib')}
    require(bindings['minizip']['sha256'] == proof['providers']['minizip']['archive_sha256'], 'minizip lineage differs')
    require(bindings['uriparser']['sha256'] == proof['providers']['uriparser']['uriparser_archive_sha256'], 'URI lineage differs')
    zreceipt = checked(bindings['zlibReceipt']['path'], proof['providers']['assimp_zlib_receipt_sha256'])
    zproof = json.loads(zreceipt.read_text())
    zidentity = [item for item in zproof.get('zlib_installed', []) if item.get('path') == 'lib/libz.a']
    require(len(zidentity) == 1 and zidentity[0].get('sha256') == bindings['zlib']['sha256'],
            'zlib archive absent from exact producer inventory')
    require(archives['zlib'] == zreceipt.parent / 'zlib-install/lib/libz.a', 'zlib artifact outside producer')
    boost = Path(bindings['boostRoot']).resolve()
    require(not any(c.isspace() or c in "'\"$;`" for c in str(boost)), 'literal Boost include path required')
    verify_inventory(boost / 'boost', {name: item['sha256'] for name, item in proof['providers']['boost']['boost_headers'].items()})
    prefix, expat = kml_root / 'install', kml_root / 'expat-install'
    libraries = [checked(prefix / 'lib' / ('libkml' + name + '.a'), proof['installed']['lib/libkml' + name + '.a']['sha256'])
                 for name in ('engine', 'dom', 'base', 'convenience', 'regionator', 'xsd')]
    libraries += [archives['minizip'], archives['uriparser'],
                  checked(expat / 'lib/libexpat.a', proof['expat_installed']['lib/libexpat.a']['sha256']), archives['zlib']]
    require(not output.exists() and not output.is_symlink(), 'fresh private configuration output required')
    for source in (kml_root, boost, *archives.values()):
        require(not output.is_relative_to(source) and not source.is_relative_to(output), 'output/dependency overlap')
    require(base_configure.count('--with-expat=no') == 1 and base_configure.count('--with-libkml=no') == 1,
            'explicit reduced GDAL configuration preimage required')
    configure = [('--with-expat=' + str(expat) if flag == '--with-expat=no' else
                  '--with-libkml=' + str(prefix) if flag == '--with-libkml=no' else flag) for flag in base_configure]
    output.mkdir(mode=0o700)
    flags = ['-Wl,--start-group', *map(str, libraries), '-Wl,--end-group']
    (output / 'libkml.pc').write_text('Name: libkml\nDescription: hash-bound public LibKML static closure\n'
        'Version: 1.3.0\nCflags: -I' + str(prefix / 'include') + ' -I' + str(boost) + '\nLibs: ' + ' '.join(flags) + '\n')
    bound_inputs = {str(receipt): receipt_sha256, str(zreceipt): digest(zreceipt)}
    for directory, inventory in ((prefix, proof['installed']), (expat, proof['expat_installed'])):
        bound_inputs.update({str(directory / name): value['sha256'] for name, value in inventory.items()})
    bound_inputs.update({str(boost / 'boost' / name): item['sha256'] for name, item in proof['providers']['boost']['boost_headers'].items()})
    bound_inputs.update({str(path): digest(path) for path in archives.values()})
    result = {'schema': 1, 'profile': 'gdal244-kml-enabled-v1', 'kmlReceiptSha256': receipt_sha256,
              'configureArguments': configure,
              'environment': {'PKG_CONFIG_LIBDIR': str(output), 'PKG_CONFIG_PATH': ''},
              'linkArguments': flags, 'requiredConfiguration': {'HAVE_EXPAT': 'yes', 'HAVE_LIBKML': 'yes'},
              'providerSha256': {str(path): digest(path) for path in libraries}, 'boundInputs': bound_inputs,
              'configuredOrBuilt': False, 'sdkOrRuntimeAcceptance': False}
    (output / 'configuration.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def allocated(root):
    seen, result = set(), 0
    for path in [root, *root.rglob('*')]:
        try:
            stat = path.lstat()
        except FileNotFoundError:
            continue  # A retired compiler temporary is not an admitted input.
        identity = stat.st_dev, stat.st_ino
        if identity not in seen:
            seen.add(identity)
            result += stat.st_blocks * 512
    return result


OUTPUT_CAP = 768 * 1024**2
RECEIPT_RESERVE = 8 * 1024**2
FREE_FLOOR = 2 * 1024**3


def gate(root, extra=0, cap=OUTPUT_CAP, reserve=RECEIPT_RESERVE):
    import shutil
    require(allocated(root) + reserve + extra <= cap, 'inclusive profile output cap: ' + str(cap))
    require(shutil.disk_usage(root).free >= FREE_FLOOR + reserve + extra, '2GiB physical floor')


def run_bounded(command, root, label, timeout, environment, capture=False, cap=OUTPUT_CAP, reserve=RECEIPT_RESERVE):
    """Parent monitors all owned allocation and complete stage diagnostics."""
    import os
    import resource
    import selectors
    import signal
    import subprocess
    import time
    started, content = time.monotonic(), bytearray()
    def child_limits():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        maximum_file = min(128 * 1024**2, cap - reserve)
        resource.setrlimit(resource.RLIMIT_FSIZE, (maximum_file, maximum_file))
    gate(root, cap=cap, reserve=reserve)
    child = subprocess.Popen(list(map(str, command)), cwd=root, env=environment,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True, preexec_fn=child_limits)
    try:
        with (root / (label + '.log')).open('xb') as stream, selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map() or child.poll() is None:
                gate(root, cap=cap, reserve=reserve)
                require(time.monotonic() - started < timeout, 'GDAL profile stage deadline: ' + label)
                for key, _ in selector.select(.05):
                    block = os.read(key.fileobj.fileno(), 32768)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    require(len(content) + len(block) <= 8 * 1024**2, 'GDAL profile stage diagnostic bound')
                    gate(root, len(block) + 4096, cap=cap, reserve=reserve)
                    stream.write(block)
                    stream.flush()
                    content.extend(block)
            require(child.wait() == 0, 'first GDAL profile command failure: ' + label)
        gate(root, cap=cap, reserve=reserve)
        return bytes(content) if capture else None
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        child.stdout.close()


def rebuild(source, out, configuration, proj_prefix, zlib_prefix, cmake, environment, run):
    """Fresh genuine GDAL compilation only; no Kernel translation units."""
    import shutil
    build, install = out / 'gdal-kml-build', out / 'gdal-kml-install'
    source_inventory = {p.relative_to(source).as_posix(): digest(p) for p in source.rglob('*') if p.is_file()}
    shutil.copytree(source, build)
    environment.update(configuration['environment'])
    command = [str(build / 'configure'), '--prefix=' + str(install), '--with-proj=' + str(proj_prefix),
               '--with-libz=' + str(zlib_prefix), *configuration['configureArguments']]
    run([cmake, '-E', 'chdir', build, *command], 'gdal-kml-configure', 180)
    text = (out / 'gdal-kml-configure.log').read_text()
    require('unrecognized options' not in text, 'unsupported GDAL KML configure options')
    opts = (build / 'GDALmake.opt').read_text()
    for name, expected in configuration['requiredConfiguration'].items():
        require(re.search(r'^' + name + r'\s*=\s*' + expected + r'\s*$', opts, re.M), 'required GDAL driver disabled: ' + name)
    require(re.search(r'^PROJ_STATIC\s*=\s*yes\s*$', opts, re.M) and '-DPROJ_VERSION=4' in opts,
            'qualified legacy static PROJ contract required')
    require('GDAL_FORMATS := $(GDAL_FORMATS) pdf' not in opts, 'PDF driver exclusion changed')
    # The generated flags must contain the exact verified static provider group.
    for path in configuration['providerSha256']:
        require(path in opts, 'qualified static KML provider absent from generated flags')
    run(['/usr/bin/make', '-C', build, '-j1', 'lib-target'], 'gdal-kml-build', 2400)
    (install / 'lib').mkdir(parents=True)
    run(['/usr/bin/make', '-C', build, '-j1', 'install-static-lib'], 'gdal-kml-install', 180)
    require(source_inventory == {p.relative_to(source).as_posix(): digest(p) for p in source.rglob('*') if p.is_file()},
            'official reference source changed during KML build')
    require(all(digest(build / name) == expected for name, expected in source_inventory.items()),
            'actual compiled GDAL source postimage changed')
    build_inventory = owned_gnu_build_inventory(build)
    return install, {'profile': 'gdal244-kml-enabled-v1', 'sourcePostimages': source_inventory,
                     'buildInventory': build_inventory,
                     'configuration': {key: value for key, value in configuration.items() if key != 'boundInputs'}, 'configureArgv': command,
                     'generatedOptionsSha256': digest(build / 'GDALmake.opt'),
                     'installed': {p.relative_to(install).as_posix(): digest(p) for p in install.rglob('*') if p.is_file()},
                     'freshGdalCompilation': True, 'kernelTranslationUnitsBuilt': 0}


def owned_gnu_build_inventory(root):
    """Only the one relative libtool metadata link in this fresh GNU tree is allowed."""
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
            'canonical owned GNU build directory required')
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            require(name == '.libs/libgdal.la' and str(path.readlink()) == '../libgdal.la',
                    'unexpected GNU build symlink')
            target = root / 'libgdal.la'
            require(target.is_file() and not target.is_symlink() and path.resolve(strict=True) == target,
                    'GNU metadata link must resolve to its exact internal regular file')
            links[name] = {'target': '../libgdal.la', 'referent': 'libgdal.la', 'sha256': digest(target)}
        elif path.is_file():
            files[name] = digest(path)
        else:
            require(path.is_dir(), 'nonregular GNU build payload rejected')
    require(set(links) == {'.libs/libgdal.la'}, 'expected GNU metadata symlink required')
    require(links['.libs/libgdal.la']['sha256'] == files.get('libgdal.la'), 'GNU link referent inventory differs')
    return {'schema': 1, 'regularFiles': files, 'symlinks': links}


def legacy_gnu_build_inventory(snapshot):
    """Compare the preserved failed producer's original flat inventory, without relabeling it."""
    require(snapshot.get('schema') == 1 and set(snapshot['symlinks']) == {'.libs/libgdal.la'},
            'owned GNU snapshot schema required')
    return {**snapshot['regularFiles'], '.libs/libgdal.la': snapshot['symlinks']['.libs/libgdal.la']['sha256']}
