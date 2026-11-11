#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline, opt-in genuine SQLCipher C component and source-built prerequisites."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tarfile
import time

HERE = Path(__file__).resolve().parent
HELPERS = {'native': HERE.parent / 'native-deps/build.py', 'las': HERE.parent / 'native-las/build.py'}
MODULES = {}
for name, path in HELPERS.items():
    spec = importlib.util.spec_from_file_location('sqlcipher_' + name, path)
    MODULES[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULES[name])
native, las = MODULES['native'], MODULES['las']
PINNED = {'schema_version': 1,
 'archives': {'tcl': {'url': 'https://prdownloads.sourceforge.net/tcl/tcl8.6.18-src.tar.gz',
                      'sha256': '14f9af32b1767ff718477a8f974ad03c34341097e6b43f4ce54644ee974e268e',
                      'bytes': 11816279,
                      'root': 'tcl8.6.18',
                      'members': 2439,
                      'regular_files': 2280,
                      'expanded_bytes': 49541245},
              'openssl': {'url': 'https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz',
                          'sha256': '603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a',
                          'bytes': 53279637,
                          'root': 'openssl-3.5.9',
                          'members': 6078,
                          'regular_files': 5779,
                          'expanded_bytes': 131230833},
              'sqlcipher': {'url': 'https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/9f6893dd657feacc35ec5de03dad721c2e44170e/takthirdparty/distfiles/sqlcipher.tar.gz',
                            'sha256': 'b670845f28da0a3c717e991e9f18a334e08f6bc977190bbce6be864ca229f96d',
                            'bytes': 19015767,
                            'root': 'sqlcipher-4.5.7',
                            'members': 2261,
                            'regular_files': 2196,
                            'expanded_bytes': 117065594}},
 'licenses': {'tcl8.6.18/license.terms': 'c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16',
              'tcl8.6.18/libtommath/LICENSE': '2fa64b163659f41965c9815882a8296d3d03ff546b76153e11445f9bdecf955a',
              'tcl8.6.18/compat/zlib/README': '4026d921213bb2e311d8d42b44ef53361c102d5d45ae32f93f8e52eaee8d068f',
              'openssl-3.5.9/LICENSE.txt': '7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a',
              'sqlcipher-4.5.7/LICENSE.md': '09e4af560ce2e3c9c2aa6b564e35947b03db7d1ae345f22a32793ed46542cc14'},
 'provenance': {'openssl_commit': '45e844fa2a14ec92d146bd8f5778ac130b6625fb',
                'openssl_checksum': 'publisher-sha256',
                'openssl_lts_until': '2030-04-08',
                'tcl_mirror_commit': '515167c897a7c8066abfbd71e8fe7bd8bf3569de',
                'tcl_fossil': 'b0a0551c13a3dbba2dac30ab9b8df30d91cc1dff292f170e19980a5e4168df83',
                'tcl_checksum': 'computed-official-designated-distribution',
                'sqlcipher_commit': '2d6941f26daa3d270bd7daad36dfba5bd6f3d12f',
                'sqlcipher_sqlite_version': '3.45.3'},
 'tools': {'cc': '14.2.0',
           'make': '4.4.1',
           'perl': '5.40.1',
           'ar': '2.44',
           'ranlib': '2.44',
           'readelf': '2.44'}}
FILES = ('build.py', 'inputs.lock.json', 'SqlcipherSourceProbe.c', 'OpenSSLSourceProbe.c')
FLAGS = ('-DSQLCIPHER_CRYPTO_OPENSSL -DSQLITE_THREADSAFE=1 -DSQLITE_ENABLE_MEMORY_MANAGEMENT=1 '
         '-DSQLITE_DEFAULT_JOURNAL_SIZE_LIMIT=1048576 -DSQLITE_ENABLE_FTS3 '
         '-DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_RTREE=1 -DSQLITE_TEMP_STORE=3 -DSQLITE_HAS_CODEC')
PROBES = ('openssl-control', 'libcrypto-pic-probe.so', 'sqlcipher-consumer',
          'libsqlcipher-pic-probe.so', 'encrypted-control.db')


def recipe():
    return {name: native.digest(HERE / name) for name in FILES} | {
        '../' + str(path.relative_to(HERE.parent)): native.digest(path) for path in HELPERS.values()}


def validate_lock(lock):
    if lock != PINNED:
        raise ValueError('source/tool/license identities differ from reviewed pins')


def validate_paths(output, cache):
    output, cache = native.external(output), native.external(cache)
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('output must be new and separate from cache')
    return output, cache


def environment(tools, output):
    env = las.environment({'cc': tools['cc'], 'cxx': tools['cc']})
    for key in list(env):
        if (key.startswith(('TCL', 'PERL', 'OPENSSL_', 'ac_cv_', 'CONFIG_', 'MAKE')) or key.startswith('LD_') or
                key in ('SHELLOPTS', 'BASHOPTS', 'AR', 'RANLIB', 'CC', 'CXX', 'SHELL', 'CDPATH')):
            env.pop(key, None)
    env.update(CC=tools['cc']['path'], AR=tools['ar']['path'], RANLIB=tools['ranlib']['path'],
               LC_ALL='C', CONFIG_SITE='/dev/null', OPENSSL_CONF='/dev/null',
               OPENSSL_MODULES=str(output / 'absent-provider-modules'),
               PERL=tools['perl']['path'])
    return env


def unpack(archive, destination, entry):
    records = las.unpack(archive, destination, entry['root'], entry)
    # Preserve genuine release mtimes so Tcl need not regenerate source stubs
    # before its self-built interpreter exists. Never copy host Tcl outputs.
    with tarfile.open(archive) as source:
        for member in source:
            if member.isfile():
                path = destination / native.relative(member.name)
                os.utime(path, (member.mtime, member.mtime))
    return records


def check_sources(source, expected):
    found = {}
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('source symlink refused')
        if path.is_file():
            found[str(path.relative_to(source))] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    if found != expected:
        raise ValueError('source inventory changed')


def audit_tcl(text):
    if (not re.search(r'^NATIVE_TCLSH\s*=\s*\./\$\{TCL_EXE\}\s*$', text, re.M) or
            not re.search(r'^ZLIB_OBJS\s*=\s*Zadler32.o', text, re.M) or
            re.search(r'^(?:LIBS|ZLIB_LIBS)\s*=.*(?:^|\s)-lz(?:\s|$)', text, re.M)):
        raise ValueError('Tcl self-bootstrap/bundled-zlib profile differs')


def audit_headers(text, prefix):
    paths = [Path(p).resolve() for p in re.findall(r'/(?:[^\s\\]+)', text) if '/openssl/' in p]
    if len(paths) < 10 or any(not p.is_relative_to(prefix.resolve()) or not p.is_file() for p in paths):
        raise ValueError('OpenSSL headers leave verified prefix')
    return {str(p): native.digest(p) for p in paths}


def runtime_closure(text):
    allowed = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'ld-linux-x86-64.so.2'}
    result = {}
    for line in text.splitlines():
        if not line.strip() or 'linux-vdso.so.1' in line:
            continue
        match = re.search(r'(?:=>\s*)?(/[^\s()]+)', line)
        if not match or Path(match[1]).name not in allowed:
            raise ValueError('foreign native runtime dependency')
        path = Path(match[1]).resolve()
        if not path.is_file():
            raise ValueError('runtime dependency missing')
        result[str(path)] = native.digest(path)
    if not result:
        raise ValueError('runtime closure empty')
    return result


def probes(output):
    result = {}
    for name in PROBES:
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('probe output missing or nonregular')
        result[name] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return result


def verify_probes(output, expected):
    if set(expected) != set(PROBES) or probes(output) != expected:
        raise ValueError('probe output integrity mismatch')


@contextlib.contextmanager
def working(directory):
    previous = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=1)
    for name, default in [('cc', 'gcc'), ('make', 'make'), ('perl', 'perl'), ('ar', 'ar'),
                          ('ranlib', 'ranlib'), ('readelf', 'readelf'), ('ldd', 'ldd')]:
        parser.add_argument('--' + name, default=default)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 is validated')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    start_recipe = recipe()
    output, cache = validate_paths(args.output, args.cache)
    # Refuse absent/tampered cache before creating a build root; no network path.
    archives = {name: native.acquire(cache, entry, False) for name, entry in lock['archives'].items()}
    output.mkdir(parents=True)
    output.chmod(0o700)
    started = time.monotonic()
    try:
        if shutil.disk_usage(output).free < 2 * 1024 ** 3:
            raise ValueError('at least 2 GiB free disk required')
        tools = {}
        for name in ('cc', 'make', 'perl', 'ar', 'ranlib', 'readelf', 'ldd'):
            resolved = Path(shutil.which(getattr(args, name)) or getattr(args, name)).resolve()
            if not resolved.is_file():
                raise ValueError('required tool missing')
            tool_env = environment({'cc': {'path': str(resolved)}, 'ar': {'path': 'ar'},
                                    'ranlib': {'path': 'ranlib'}, 'perl': {'path': 'perl'}}, output)
            version = native.run([str(resolved), '--version'], output, 'tool-' + name,
                                 capture=True, env=tool_env).decode().strip()
            tools[name] = {'path': str(resolved), 'sha256': native.digest(resolved), 'version': version}
        for name, version in lock['tools'].items():
            if not re.search(r'(?<![0-9.])' + re.escape(version) + r'(?![0-9.])', tools[name]['version']):
                raise ValueError('toolchain differs from recorded profile')
        env = environment(tools, output)
        sources = output / 'source'
        sources.mkdir()
        records = {}
        for name, entry in lock['archives'].items():
            records.update(unpack(archives[name], sources, entry))
        (output / 'source-inputs.json').write_text(json.dumps(records, indent=2) + '\n')
        notices = output / 'licenses'
        notices.mkdir()
        for name, digest in lock['licenses'].items():
            path = sources / native.relative(name)
            if native.digest(path) != digest:
                raise ValueError('license source checksum mismatch')
            shutil.copyfile(path, notices / name.replace('/', '__'))
        for name in ('SqlcipherSourceProbe.c', 'OpenSSLSourceProbe.c'):
            shutil.copyfile(HERE / name, output / name)
        roots = {name: sources / entry['root'] for name, entry in lock['archives'].items()}
        stage = time.monotonic()

        def command(name, argv, cwd, child_env=None, capture=False):
            remaining = min(1200 - (time.monotonic() - stage), 2700 - (time.monotonic() - started))
            if remaining <= 0:
                raise ValueError('stage or total build deadline exceeded')
            las.disk_usage(output, cache)
            with working(cwd):
                result = native.run(list(map(str, argv)), output, name, timeout=remaining,
                                    env=child_env or env, capture=capture)
            las.disk_usage(output, cache)
            return result.decode()

        tbuild, tprefix = output / 'tcl-build', output / 'tcl-install'
        tbuild.mkdir()
        tenv = env | {'ac_cv_path_tclsh': str(output / 'absent-bootstrap-tcl'), 'ac_cv_header_zlib_h': 'no'}
        command('tcl-configure', [roots['tcl'] / 'unix/configure', '--prefix=' + str(tprefix),
                '--disable-shared', '--disable-threads', '--disable-load', 'CFLAGS=-O2 -fPIC'], tbuild, tenv)
        audit_tcl((tbuild / 'Makefile').read_text())
        command('tcl-build', [tools['make']['path'], '-j' + str(args.jobs), 'tclsh'], tbuild, tenv)
        command('tcl-install', [tools['make']['path'], 'install-binaries', 'install-libraries'], tbuild, tenv)
        closure = runtime_closure(command('tcl-closure', [tools['ldd']['path'], tprefix / 'bin/tclsh8.6'], output, capture=True))
        script = output / 'tcl-control.tcl'
        script.write_text('puts "tcl=[info patchlevel] zlib_roundtrip=[expr {[zlib decompress [zlib compress {bundled-control}]] eq {bundled-control}}]"\nputs [info library]\n')
        tcl = tprefix / 'bin/tclsh8.6'
        if command('tcl-control', [tcl, script], output, capture=True).splitlines() != [
                'tcl=8.6.18 zlib_roundtrip=1', str(tprefix / 'lib/tcl8.6')]:
            raise ValueError('source-built Tcl control differs')
        stage = time.monotonic()
        obuild, oprefix = output / 'openssl-build', output / 'openssl-install'
        obuild.mkdir()
        command('openssl-configure', [tools['perl']['path'], roots['openssl'] / 'Configure',
                'linux-x86_64', 'no-shared', 'no-tests', '--prefix=' + str(oprefix), '--libdir=lib', '-O2', '-fPIC'], obuild)
        command('openssl-build', [tools['make']['path'], '-j' + str(args.jobs), 'build_libs'], obuild)
        command('openssl-install', [tools['make']['path'], 'install_dev'], obuild)
        crypto, inc = oprefix / 'lib/libcrypto.a', oprefix / 'include'
        if crypto.is_symlink() or not crypto.is_file() or list((oprefix / 'lib').glob('libcrypto.so*')):
            raise ValueError('expected genuine static-only libcrypto prefix')
        compiler = tools['cc']['path']
        command('openssl-control-link', [compiler, '-I' + str(inc), output / 'OpenSSLSourceProbe.c',
                crypto, '-Wl,--no-undefined', '-ldl', '-pthread', '-o', output / 'openssl-control'], output)
        if command('openssl-control', [output / 'openssl-control'], output, capture=True).splitlines() != [
                'OpenSSL 3.5.9 29 Sep 2026', 'SHA256-positive=PASS']:
            raise ValueError('OpenSSL positive control differs')
        command('openssl-pic', [compiler, '-shared', '-Wl,--no-undefined', '-Wl,--whole-archive', crypto,
                '-Wl,--no-whole-archive', '-ldl', '-pthread', '-o', output / 'libcrypto-pic-probe.so'], output)
        if 'TEXTREL' in command('openssl-pic-elf', [tools['readelf']['path'], '-d', output / 'libcrypto-pic-probe.so'], output, capture=True):
            raise ValueError('crypto PIC contains text relocations')
        closure.update(runtime_closure(command('openssl-closure', [tools['ldd']['path'], output / 'openssl-control'], output, capture=True)))
        stage = time.monotonic()
        build = output / 'sqlcipher-build'
        build.mkdir()
        senv = env | {'TCLSH_CMD': str(tcl), 'CPPFLAGS': '-I' + str(inc) + ' ' + FLAGS,
                      'CFLAGS': '-O2 -fPIC', 'LDFLAGS': '-L' + str(crypto.parent), 'LIBS': str(crypto) + ' -ldl -pthread'}
        command('sqlcipher-configure', [roots['sqlcipher'] / 'configure', '--disable-shared', '--enable-static',
                '--disable-tcl', '--disable-readline', '--with-crypto-lib=openssl', '--prefix=' + str(output / 'sqlcipher-install')], build, senv)
        if not re.search(r'^TCLSH_CMD\s*=\s*' + re.escape(str(tcl)) + r'\s*$', (build / 'Makefile').read_text(), re.M):
            raise ValueError('SQLCipher selected foreign Tcl')
        command('sqlcipher-amalgamation', [tools['make']['path'], '-j' + str(args.jobs), 'sqlite3.c', 'sqlite3.h', 'TCLSH_CMD=' + str(tcl)], build, senv)
        headers = audit_headers(command('sqlcipher-header-dependencies', [compiler, '-M', '-DSQLITE_HAS_CODEC',
                '-DSQLCIPHER_CRYPTO_OPENSSL', '-I' + str(inc), build / 'sqlite3.c'], build, capture=True), inc)
        command('sqlcipher-compile', [compiler, '-O2', '-fPIC', '-I' + str(inc), *FLAGS.split(), '-c', 'sqlite3.c', '-o', 'sqlite3.o'], build)
        library = build / 'libsqlite3.a'
        command('sqlcipher-archive', [tools['ar']['path'], 'rcs', library, build / 'sqlite3.o'], build)
        command('sqlcipher-consumer-link', [compiler, '-O2', '-DSQLITE_HAS_CODEC', '-I' + str(build), '-I' + str(inc),
                output / 'SqlcipherSourceProbe.c', library, crypto, '-Wl,--no-undefined', '-ldl', '-pthread', '-lm', '-o', output / 'sqlcipher-consumer'], output)
        control = command('sqlcipher-consumer', [output / 'sqlcipher-consumer', output / 'encrypted-control.db'], output, capture=True)
        if control.splitlines() != ['cipher_version=4.5.7 community', 'openssl=OpenSSL 3.5.9 29 Sep 2026',
                                    'sqlite=3.45.3', 'encrypt_reopen_wrong_key=PASS']:
            raise ValueError('SQLCipher positive controls differ')
        command('sqlcipher-pic', [compiler, '-shared', '-Wl,--no-undefined', '-Wl,--whole-archive', library, crypto,
                '-Wl,--no-whole-archive', '-ldl', '-pthread', '-lm', '-o', output / 'libsqlcipher-pic-probe.so'], output)
        if 'TEXTREL' in command('sqlcipher-pic-elf', [tools['readelf']['path'], '-d', output / 'libsqlcipher-pic-probe.so'], output, capture=True):
            raise ValueError('SQLCipher PIC contains text relocations')
        closure.update(runtime_closure(command('sqlcipher-closure', [tools['ldd']['path'], output / 'sqlcipher-consumer'], output, capture=True)))
        install = output / 'sqlcipher-install'
        (install / 'lib').mkdir(parents=True)
        (install / 'include').mkdir()
        shutil.copyfile(library, install / 'lib/libsqlite3.a')
        shutil.copyfile(build / 'sqlite3.h', install / 'include/sqlite3.h')
        shutil.copyfile(build / 'sqlite3ext.h', install / 'include/sqlite3ext.h')
        check_sources(sources, records)
        for item in tools.values():
            if native.digest(Path(item['path'])) != item['sha256']:
                raise ValueError('tool changed during build')
        for name, path in archives.items():
            native.verified(path, lock['archives'][name])
        if time.monotonic() - started > 2700:
            raise ValueError('total build deadline exceeded')
        if recipe() != start_recipe:
            raise ValueError('recipe changed during build')
        result = {'recipe': start_recipe, 'tools': tools, 'archives': lock['archives'], 'licenses': lock['licenses'],
                  'source_files': len(records), 'source_posthash_verified': True, 'headers': headers,
                  'runtime_closure': closure, 'probe_outputs': probes(output),
                  'installed': {name: native.inventory(path) for name, path in [('tcl', tprefix), ('openssl', oprefix), ('sqlcipher', install)]},
                  'elapsed_seconds': time.monotonic() - started, 'owned_bytes': las.disk_usage(output, cache),
                  'encryption_controls': True, 'whole_archive_PIC': True, 'fresh_entrypoint': True,
                  'historical_version_security_acceptance': False, 'target_ABI_acceptance': False,
                  'full_SDK_acceptance': False, 'TAKX_acceptance': False}
        (output / 'complete.json').write_text(json.dumps(result, indent=2) + '\n')
        print('Complete genuine SQLCipher C component proof: ' + str(output / 'complete.json'))
    except Exception as error:
        (output / 'failed.json').write_text(json.dumps({'type': type(error).__name__,
                'message': 'Local source build failed; inspect private bounded logs. No complete proof inferred.'}) + '\n')
        raise


if __name__ == '__main__':
    main()
