#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Separately validate a known failed GNU-inventory attempt; never rebuild or rerun JNI."""
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


producer = module('finalization_producer', HERE / 'build.py')
kml = producer.kml
sha = kml.digest
require = kml.require


def read(path):
    require(path.is_file() and not path.is_symlink(), 'regular evidence file required')
    return json.loads(path.read_text())


def checked_regular_evidence(path, expected_sha):
    """Hash-only inputs are not pkg-config tokens; preserve their exact literal filenames."""
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            'canonical regular evidence file required')
    require(re.fullmatch('[0-9a-f]{64}', expected_sha) and sha(path) == expected_sha,
            'bound evidence SHA differs')
    return path


def original_inventory(root):
    """Generic files remain regular; the sole GNU metadata link is checked separately."""
    snapshot = kml.owned_gnu_build_inventory(root / 'gdal-kml-build')
    files = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            require(name == 'gdal-kml-build/.libs/libgdal.la', 'unexpected original execution link')
        elif path.is_file():
            files[name] = sha(path)
        else:
            require(path.is_dir(), 'nonregular original evidence rejected')
    return {'schema': 1, 'regularFiles': files, 'gnuBuild': snapshot}


def git_source(repo, revision, name):
    relative = Path(name)
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe original recipe path')
    return subprocess.check_output(['/usr/bin/git', '-C', str(repo), 'show', revision + ':takx/' + name],
                                   env={'PATH':'/usr/bin:/bin','LC_ALL':'C','GIT_NO_LAZY_FETCH':'1','GIT_CONFIG_NOSYSTEM':'1',
                                        'GIT_CONFIG_GLOBAL':'/dev/null'}, timeout=10)


def metadata_tool(tool, arguments):
    """Only hash-pinned readelf/nm inspect already pinned ELF files; no ldd/load/execute."""
    child = subprocess.Popen([str(tool), *map(str, arguments)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                             env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    try:
        stdout, stderr = child.communicate(timeout=20)
    except BaseException:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        raise
    require(child.returncode == 0, 'read-only ELF tool failed')
    require(len(stdout) <= 8 * 1024**2 and len(stderr) <= 65536, 'metadata tool output bound')
    require(not stderr, 'unexpected ELF metadata diagnostics')
    return stdout.decode('utf-8', errors='strict')


def validate(plan):
    root, repo = Path(plan['originalRoot']), Path(plan['repository'])
    require(root.is_dir() and root.resolve() == root and not root.is_symlink(), 'canonical original root required')
    require(not (root / 'complete.json').exists(), 'original execution must remain failed, not relabeled')
    require(sha(root / 'failed.json') == plan['originalFailedSha256'], 'original failure changed')
    failed = read(root / 'failed.json')
    require(failed == {'first_failure': "ValueError('symlink inventory input')", 'kml_profile_enabled': True,
                       'last_command': 'probe', 'native_kernel_or_client_acceptance': False}, 'different original failure')
    recipe = read(root / 'recipe.json')
    require(recipe == plan['originalRecipe'], 'original executed recipe differs')
    for name, expected in recipe.items():
        require(hashlib.sha256(git_source(repo, plan['originalSourceCommit'], name)).hexdigest() == expected,
                'original source checkpoint differs: ' + name)
        if name not in ('native-gdal-jni/build.py', 'native-gdal-jni/kml_profile.py'):
            require(sha(repo / 'takx' / name) == expected, 'unmodified original helper changed: ' + name)
    expected = read(Path(plan['expectedInventoryFile']))
    require(sha(Path(plan['expectedInventoryFile'])) == plan['expectedInventorySha256'], 'plan inventory changed')
    require(original_inventory(root) == expected, 'original execution evidence changed')
    record = read(root / 'kml-build.json')
    require(kml.legacy_gnu_build_inventory(expected['gnuBuild']) == record['buildInventory'],
            'original captured flat GNU inventory differs')
    require(producer.file_hashes(root / 'gdal-kml-install') == record['installed'], 'installed GDAL differs')
    require(producer.file_hashes(root / 'source-reference/gdal/gdal') == record['sourcePostimages'],
            'official source postimages differ')
    for name, expected_sha in record['sourcePostimages'].items():
        require(sha(root / 'gdal-kml-build' / name) == expected_sha, 'actual compiled source changed')
    archive = producer.kernel.archive_members(root / 'gdal-kml-install/lib/libgdal.a')
    objects = Counter(value for name, value in expected['gnuBuild']['regularFiles'].items() if name.endswith('.o'))
    require(archive == objects and sum(archive.values()) == 1073, 'exact real GDAL archive/object closure differs')
    a = SimpleNamespace(**{name: Path(value) for name, value in plan['producerInputs'].items()})
    deps = {family: producer.b.verify_dependency(path, family)
            for family, path in (('proj', a.proj_proof), ('assimp', a.assimp_proof))}
    reference = producer.b.inventory(root / 'source-reference')
    raw = producer.kernel.verify_producer(a, reference, deps)
    artifacts, gis = producer.java.verified_gis(a.gis_build, read(repo / 'takx/kernel-java/inputs.lock.json'))
    accepted = read(root / 'accepted-inputs.json')
    require(accepted == {'native': raw, 'gis_java': gis, 'dependency_receipts': deps}, 'accepted source producers changed')
    require(sha(a.gis_build / 'build-state.json') == plan['gisReceiptSha256'], 'actual V2 GIS receipt changed')
    profile = read(repo / 'takx/gis-java/jni-exceptions-profile-v2.json')
    for name, identity in profile['sources'].items():
        require(sha(a.gis_build / 'source/gdal' / name) == identity['postSha256'], 'actual GIS source postimage differs')
    conf = read(root / 'private-pkg-config/configuration.json')
    require(conf['kmlReceiptSha256'] == plan['kmlReceiptSha256'], 'qualified KML proof identity differs')
    require(sha(Path(plan['kmlRoot']) / 'complete.json') == plan['kmlReceiptSha256'], 'qualified KML receipt changed')
    require(sha(Path(plan['kmlBindings'])) == plan['kmlBindingsSha256'], 'original private provider bindings changed')
    for path, expected_sha in conf['boundInputs'].items():
        checked_regular_evidence(path, expected_sha)
    for path, expected_sha in conf['providerSha256'].items():
        kml.checked(path, expected_sha)
    require(sha(root / 'gdal-kml-build/GDALmake.opt') == record['generatedOptionsSha256'], 'actual generated config changed')
    opts = (root / 'gdal-kml-build/GDALmake.opt').read_text()
    for name in ('HAVE_EXPAT', 'HAVE_LIBKML', 'PROJ_STATIC'):
        require(re.search(r'^' + name + r'\s*=\s*yes\s*$', opts, re.M), 'actual enabled driver/static-PROJ config differs')
    for path in conf['providerSha256']:
        require(path in opts, 'qualified static provider absent from generated config')
    tools = read(root / 'tools.json')
    for path, expected_sha in tools.items():
        kml.checked(path, expected_sha)
    commands = read(root / 'commands.json')
    require(commands == plan['originalCommands'], 'executed command history differs')
    require([step['name'] for step in commands] == plan['requiredCommandOrder'], 'missing/reordered actual stages')
    by_name = {step['name']: step['command'] for step in commands}
    require('-Xcheck:jni' in by_name['probe'] and by_name['probe'][-1] == 'GdalFormatProfileProbe',
            'actual checked-JNI controls not executed')
    require('-j1' in by_name['gdal-kml-build'] and by_name['gdal-kml-build'][-1] == 'lib-target',
            'actual focused GDAL compilation missing')
    consume = read(root / 'consumed-header-hashes.json')
    jdk = a.java_home
    header_root = root / 'source-reference/gdal/gdal'
    for name in ('gdal_wrap.cpp','gdalconst_wrap.c','gnm_wrap.cpp','ogr_wrap.cpp','osr_wrap.cpp'):
        require(sha(root / 'wrappers' / name) == sha(a.gis_build / 'generated' / name), 'frozen generated wrapper differs')
        actual = producer.consumed_headers(root / (name + '.d'),
                                           [root / 'wrappers', root / 'gdal-kml-install/include', header_root, jdk / 'include'])
        require(actual == consume[name], 'actual compiler dependency/header receipt differs')
        require((root / (name + '.o')).is_file() and not (root / (name + '.o')).is_symlink(), 'real JNI object missing')
    classes = producer.file_hashes(root / 'classes')
    require(classes and all(re.fullmatch(r'(GdalJniProbe|GdalFormatProfileProbe|GdalExceptionControls)(?:\$[A-Za-z0-9_]+)*\.class',
                                        name) for name in classes), 'unexpected control/SDK class overlay')
    products = producer.file_hashes(root / 'lib')
    require(set(products) == {'libgdal.so','libgdalalljni.so'}, 'exact two real shared products required')
    readelf, nm = Path('/usr/bin/readelf').resolve(), Path('/usr/bin/nm').resolve()
    require(str(readelf) in tools and str(nm) in tools, 'ELF inspector outside actual toolchain')
    dynamic, metadata_hashes = {}, {}
    allowed = {'libstdc++.so.6','libm.so.6','libgcc_s.so.1','libc.so.6','ld-linux-x86-64.so.2'}
    for name in products:
        path = root / 'lib' / name
        header = metadata_tool(readelf, ['-h', path])
        require('ELF64' in header and 'little endian' in header and 'Advanced Micro Devices X86-64' in header,
                'actual ELF ABI differs')
        text = metadata_tool(readelf, ['-d', path])
        needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', text)
        require('TEXTREL' not in text and needed and set(needed) <= allowed | ({'libgdal.so'} if name == 'libgdalalljni.so' else set()),
                'foreign dynamic GDAL/XML/KML provider or text relocation')
        require(re.search(r'\(SONAME\).*?\[' + re.escape(name) + r'\]', text), 'actual SONAME differs')
        if name == 'libgdalalljni.so':
            require('libgdal.so' in needed and '$ORIGIN' in text, 'shared GDAL lookup contract missing')
        dynamic[name] = needed
        metadata_hashes[name] = {'elfHeader': hashlib.sha256(header.encode()).hexdigest(),
                                 'dynamic': hashlib.sha256(text.encode()).hexdigest()}
    symbols = metadata_tool(readelf, ['--dyn-syms','--wide',root / 'lib/libgdal.so'])
    require(not re.search(r'\bXML_[A-Za-z0-9_]+', symbols), 'private Expat escaped actual dynamic symbol table')
    exported = metadata_tool(nm, ['-D','--defined-only',root / 'lib/libgdalalljni.so'])
    require(not re.search(r'\bGDALVersionInfo\b', exported), 'JNI product embeds duplicate GDAL engine')
    expected_exports = set()
    for name in consume:
        body = (root / 'wrappers' / name).read_text()
        expected_exports.update(re.findall(r'^SWIGEXPORT[^\n]*JNICALL\s+(Java_\w+)\(', body, re.M))
    actual_exports = {line.split()[-1] for line in exported.splitlines() if line.split() and line.split()[-1].startswith('Java_')}
    require(actual_exports == expected_exports, 'actual native JNI exports differ from genuine generated wrapper set')
    log = (root / 'probe.log').read_text()
    require(not producer.diagnostics.strict_jni_failures(log), 'strict JNI/critical-region warning/error observed')
    markers = ('GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true',
               'PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS',
               'PASS_GDAL_KML_DRIVERS_COORDINATES_ORIGINAL_THROWABLES')
    require(all(log.splitlines().count(marker) == 1 for marker in markers), 'actual driver/coordinate/Throwable markers missing')
    paths = {Path(line[4:]) for line in log.splitlines() if line.startswith('ELF ')}
    old = read(Path(plan['qualifiedRuntimeReference']))
    require(sha(Path(plan['qualifiedRuntimeReference'])) == plan['qualifiedRuntimeReferenceSha256'], 'qualified host runtime reference changed')
    mapped = {}
    for path in paths:
        require(path.is_file() and not path.is_symlink(), 'mapped provider file changed')
        expected_sha = products.get(path.name) if path.parent == root / 'lib' else old['bound_files'].get(str(path))
        require(expected_sha and sha(path) == expected_sha, 'unqualified mapped host/JDK/provider byte identity')
        mapped[str(path)] = expected_sha
    require({root / 'lib/libgdal.so', root / 'lib/libgdalalljni.so'} <= paths, 'actual fresh GDAL provider mapping absent')
    require(original_inventory(root) == expected, 'original evidence changed during independent validation')
    for path, expected_sha in conf['boundInputs'].items():
        checked_regular_evidence(path, expected_sha)
    for path, expected_sha in tools.items():
        kml.checked(path, expected_sha)
    return {'originalProducerSuccess': False, 'originalFailurePreserved': True,
            'actualOriginalControlsObserved': list(markers), 'strictJniDiagnosticCount': 0,
            'actualGdalArchiveObjects': sum(archive.values()), 'actualJniExports': len(actual_exports),
            'products': products, 'probeClasses': classes, 'mappedProviders': mapped,
            'dynamicNeeded': dynamic, 'elfInspectionHashes': metadata_hashes,
            'gnuMetadataSymlinks': expected['gnuBuild']['symlinks'],
            'sourceToolProviderHeaderPostchecks': True, 'fullOriginalEvidenceUnchanged': True,
            'noRecompile': True, 'noNativeRuntimeRetry': True,
            'nativeKernelSdkRendererOrClientAcceptance': False}


