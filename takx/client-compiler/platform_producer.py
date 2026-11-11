#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Rebuild the entire pinned Platform for the explicit mission-admission profile.

No acquisition, old Platform class overlay, native loading or application runtime.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import shutil
import signal
import subprocess
import time
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = HERE / 'platform-inputs.lock.json'
PROFILE = 'takx57-mission-admission-v2'
REVISION = '0b59a9bb2d0e90dc35c9edfff1c2056daab2b713'
PLATFORM_FILES = {
    'Platform/src/main/java/gov/tak/platform/datapackage/ZipReader.java',
    'Platform/src/main/java/gov/tak/platform/datapackage/PackageReader.java',
    'Platform/src/main/java/gov/tak/platform/datapackage/PackageImporter.java',
}
CLIENT_FILE = 'Client/src/main/java/gov/tak/core/comms/takserver/DataPackageManager.java'
EXTRA_CLASS = 'gov/tak/platform/datapackage/ZipReader$BoundedEntryStream.class'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def relative(name):
    require(type(name) is str, 'relative path must be text')
    path = PurePosixPath(name)
    require(name and path.parts and str(path) == name and not path.is_absolute() and '..' not in path.parts and
            '\\' not in name and not any(c in name for c in '\n\r\0'), 'unsafe relative path')
    return name


def digest_text(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.resolve() == path.absolute(),
            'regular canonical input required: ' + str(path))
    return path


def inventory(root, suffix):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'artifact/source symlink rejected')
        if path.is_file() and path.name.endswith(suffix):
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def resolve(reference, roots):
    name, path = reference.split(':', 1)
    relative(path)
    require(name in roots, 'unknown binding root')
    result = (roots[name] / path).resolve(strict=True)
    require(result.is_relative_to(roots[name]), 'bound input escapes root')
    return result


def read_profile(profile_file, expected):
    profile_file = regular(Path(profile_file).absolute())
    require(digest_text(expected) and sha(profile_file) == expected, 'mission profile SHA differs')
    profile = load(profile_file)
    require(profile['schema'] == 1 and profile['profileId'] == PROFILE and profile['sourceRevision'] == REVISION,
            'unsupported mission source profile')
    require(set(profile['sources']) == PLATFORM_FILES | {CLIENT_FILE}, 'exact four production postimages required')
    for name, entry in profile['sources'].items():
        require(digest_text(entry['preSha256']) and digest_text(entry['postSha256']) and
                entry['scope'] == ('Platform' if name in PLATFORM_FILES else 'Client'), 'invalid mission source identity')
    require(profile['platformReceipt']['requiredProducer'] == 'genuine-full-platform' and
            profile['platformReceipt']['oldPlatformArtifactAllowed'] is False and
            profile['platformReceipt']['newClassNames'] == [EXTRA_CLASS], 'old/unknown Platform artifact policy')
    patch = regular(profile_file.parent / relative(profile['patch']['file']))
    require(patch.resolve().is_relative_to(profile_file.parent) and sha(patch) == profile['patch']['sha256'],
            'mission patch identity differs')
    return profile, profile_file, patch


def expected_sources(lock, profile):
    result = dict(lock['sources'])
    for name in PLATFORM_FILES:
        reference = 'takx-client-readiness:5.7/' + name
        require(result.get(reference) == profile['sources'][name]['preSha256'], 'Platform preimage differs from producer lock')
        result[reference] = profile['sources'][name]['postSha256']
    return result


def verify_platform_proof(profile_file, expected_profile_sha256, proof_root, expected_receipt_sha256):
    """Consumer gate: one complete producer artifact, never a two-class overlay."""
    profile, profile_file, _ = read_profile(profile_file, expected_profile_sha256)
    root = Path(proof_root).absolute()
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root, 'canonical Platform proof root required')
    receipt_file = regular(root / 'complete.json')
    require(digest_text(expected_receipt_sha256) and sha(receipt_file) == expected_receipt_sha256,
            'reviewed full Platform receipt SHA required')
    receipt = load(receipt_file)
    lock = load(LOCK)
    require(receipt.get('producer') == 'genuine-full-platform' and receipt.get('compilerSuccess') is True,
            'full genuine Platform producer success required')
    require(receipt.get('sourceCount') == 1815 and receipt.get('returncode') == 0,
            'complete successful Platform compiler command required')
    require(receipt.get('producerRecipeSha256') == sha(Path(__file__)) and
            receipt.get('producerInputsSha256') == sha(LOCK), 'Platform producer recipe/lock differs')
    require(receipt.get('profileId') == PROFILE and receipt.get('profileSha256') == expected_profile_sha256 and
            receipt.get('patchSha256') == profile['patch']['sha256'] and receipt.get('sourceRevision') == REVISION,
            'Platform producer mission profile/patch differs')
    postimages = {name: profile['sources'][name]['postSha256'] for name in sorted(PLATFORM_FILES)}
    require(receipt.get('platformSourcePostimages') == postimages and
            receipt.get('sourceInventory') == expected_sources(lock, profile), 'full Platform source/postimage lineage differs')
    require(receipt.get('artifactClassDirectory') == 'classes', 'fixed authoritative Platform artifact required')
    classes = root / 'classes'
    generated = root / 'generated'
    require(classes.is_dir() and generated.is_dir() and not classes.is_symlink() and not generated.is_symlink(),
            'regular authoritative class/generated directories required')
    actual = inventory(classes, '.class')
    require(set(actual) == set(lock['expected_baseline_class_names']) | {EXTRA_CLASS} and
            receipt.get('classInventory') == actual, 'complete rebuilt Platform class inventory differs')
    require({p.relative_to(classes).as_posix() for p in classes.rglob('*') if p.is_file()} == set(actual),
            'unexpected non-class Platform artifact')
    actual_generated = inventory(generated, '.java')
    require(set(actual_generated) == set(lock['expected_generated_source_names']) and
            receipt.get('generatedInventory') == actual_generated, 'actual Platform annotation outputs differ')
    require(receipt.get('inputPostchecksPassed') is True and receipt.get('runtimeOrClientAcceptance') is False,
            'Platform input postcheck/scope missing')
    require(sha(regular(root / 'sources.args')) == receipt.get('sourceArgumentsSha256'),
            'actual Platform source arguments differ')
    return {'classesPath': classes, 'classInventory': actual, 'generatedInventory': actual_generated,
            'profileId': PROFILE, 'profileSha256': expected_profile_sha256,
            'patchSha256': profile['patch']['sha256'], 'sourceRevision': REVISION,
            'platformSourcePostimages': postimages, 'receiptSha256': expected_receipt_sha256}


def allocated(root):
    seen, result = set(), 0
    if not root.exists():
        return 0
    for path in [root, *root.rglob('*')]:
        try:
            entry = path.lstat()
        except FileNotFoundError:
            continue  # Retired compiler temporary; never admits an input.
        identity = entry.st_dev, entry.st_ino
        if identity not in seen:
            seen.add(identity)
            result += entry.st_blocks * 512
    return result


def verify_inputs(lock, roots):
    for reference, digest in {**lock['files'], **lock['sources']}.items():
        require(sha(resolve(reference, roots)) == digest, 'Platform input changed: ' + reference)
    for reference, expected in lock['class_directories'].items():
        require(inventory(resolve(reference, roots), '.class') == expected, 'frozen prerequisite class membership differs')
    for reference, names in lock['source_directories'].items():
        require(sorted(inventory(resolve(reference, roots), '.java')) == names, 'complete source directory membership differs')


def projection(profile, profile_sha, patch_sha, root, expected_receipt_sha):
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root, 'canonical projection root required')
    receipt = regular(root / 'projection.json')
    require(digest_text(expected_receipt_sha) and sha(receipt) == expected_receipt_sha, 'reviewed projection receipt SHA required')
    data = load(receipt)
    require(data.get('schema') == 1 and data.get('profileId') == PROFILE and data.get('profileSha256') == profile_sha and
            data.get('patchSha256') == patch_sha and data.get('sourceRevision') == REVISION and
            data.get('sources') == profile['sources'], 'mission projection/profile differs')
    source = root / 'source'
    require(source.is_dir() and not source.is_symlink(), 'production projection source tree required')
    files = inventory(source, '.java')
    require(files == {name: entry['postSha256'] for name, entry in profile['sources'].items()},
            'exact four source postimages required; no extra SDK definitions')
    require({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} == set(files),
            'unexpected projection source payload')
    return {name: regular(source / name) for name in files}, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--projection', type=Path, required=True)
    parser.add_argument('--projection-sha256', required=True)
    parser.add_argument('--check-inputs', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    recipe_sha, lock_sha = sha(Path(__file__)), sha(LOCK)
    lock = load(LOCK)
    bindings = load(args.bindings)
    require(set(bindings) == set(lock['roots']) and all(Path(p).is_absolute() for p in bindings.values()),
            'exact absolute Platform binding roots required')
    roots = {name: Path(path).resolve(strict=True) for name, path in bindings.items()}
    require(all(not any(character in str(path) for character in '\n\r\0' + os.pathsep) for path in roots.values()),
            'binding root cannot contain classpath/argument separators')
    profile, profile_file, patch = read_profile(args.profile, args.profile_sha256)
    require(lock['official_revision'] == REVISION, 'unsupported Platform source revision')
    projected, projection_receipt = projection(profile, args.profile_sha256, sha(patch), args.projection,
                                               args.projection_sha256)
    verify_inputs(lock, roots)
    source_inventory = expected_sources(lock, profile)
    source_paths = {}
    for reference in sorted(lock['sources']):
        mission_path = reference.removeprefix('takx-client-readiness:5.7/')
        source_paths[reference] = projected[mission_path] if mission_path in PLATFORM_FILES else resolve(reference, roots)
        require(sha(source_paths[reference]) == source_inventory[reference], 'actual compiled source differs')
    require(len(source_paths) == 1815, 'entire pinned Platform source set required')
    cp = [resolve(reference, roots) for reference in lock['classpath']]
    pp = [resolve(reference, roots) for reference in lock['processorpath']]
    require(all(not any(character in str(path) for character in '\n\r\0' + os.pathsep)
                for path in [*source_paths.values(), *cp, *pp]), 'input path contains unsupported separators')
    require(len(cp) == 135 and len(pp) == 129, 'complete Platform dependency closure required')
    require(not any(path.name == 'platform-classes' for path in cp), 'old Platform artifact must not appear on compiler CP')
    mission_classes = {name.removeprefix('Platform/src/main/java/').removesuffix('.java') + '.class'
                       for name in PLATFORM_FILES}
    for path in cp:
        if path.is_dir():
            require(not any((path / name).exists() for name in mission_classes), 'duplicate mission Platform definition on CP')
        else:
            with zipfile.ZipFile(path) as archive:
                require(not mission_classes.intersection(archive.namelist()), 'duplicate mission Platform definition in JAR')
    if args.check_inputs:
        print('Verified full Platform source, projection and prerequisites; no compiler launched')
        return
    require(args.output is not None, 'fresh explicit output required')
    out = args.output.absolute()
    require(not out.exists() and not out.is_symlink(), 'fresh Platform output required')
    for root in [*roots.values(), profile_file.parent, Path(args.projection).resolve(), HERE]:
        require(not out.is_relative_to(root) and not root.is_relative_to(out), 'Platform output/input overlap rejected')
    limits = lock['limits']
    require(shutil.disk_usage(out.parent).free >= limits['minimum_free_bytes'] + limits['allocated_output_bytes'],
            'full 24MiB reservation above physical floor required')
    out.mkdir(mode=0o700)
    for name in ['classes', 'generated', 'empty', 'tmp']:
        (out / name).mkdir()
    arguments = out / 'sources.args'
    arguments.write_text(''.join('"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"\n'
                                 for path in source_paths.values()))
    javac = resolve(lock['javac'], roots)
    command = [str(javac), '-J-Xmx768m', '-J-XX:ActiveProcessorCount=2', '-J-Djava.io.tmpdir=' + str(out / 'tmp'),
               '--release', '17', '-encoding', 'UTF-8', '-implicit:none', '-sourcepath', str(out / 'empty'),
               '-Xmaxerrs', '2000', '-cp', os.pathsep.join(map(str, cp)), '-d', str(out / 'classes'),
               '-processor', ','.join(lock['processors']), '-processorpath', os.pathsep.join(map(str, pp)),
               '-AeventBusIndex=gov.takx.core.event.PlatformEventIndex', '-s', str(out / 'generated'), '@' + str(arguments)]
    bound = {str(path): sha(path) for path in [Path(__file__), LOCK, profile_file, patch, projection_receipt, arguments, *projected.values()]}
    started = time.monotonic()
    failure = None
    code = None
    raw = bytearray()
    def gate(extra=0, reserve=True):
        held = limits['receipt_reserve_bytes'] if reserve else 0
        require(allocated(out) + held + extra <= limits['allocated_output_bytes'], '24MiB inclusive Platform cap')
        require(shutil.disk_usage(out).free >= limits['minimum_free_bytes'] + held + extra, '2GiB physical floor')
    def verify_all():
        verify_inputs(lock, roots)
        for path, digest in bound.items():
            require(sha(path) == digest, 'profile/projection/producer changed')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('JAVA_', 'JDK_', 'LD_')) and key not in ('_JAVA_OPTIONS', 'CLASSPATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY')}
    env.update(TMPDIR=str(out / 'tmp'), LC_ALL='C.UTF-8')
    def child_limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        gate()
        child = subprocess.Popen(command, cwd=out, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=child_limits)
        with (out / 'platform.log').open('xb') as log, selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            try:
                while selector.get_map() or child.poll() is None:
                    gate()
                    require(time.monotonic() - started < limits['compile_seconds'], 'Platform compile deadline')
                    for key, _ in selector.select(.05):
                        block = os.read(key.fileobj.fileno(), 32768)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = limits['log_bytes'] - len(raw)
                        piece = block[:remaining]
                        gate(len(piece) + 4096)
                        log.write(piece)
                        log.flush()
                        raw.extend(piece)
                        require(len(piece) == len(block), 'bounded Platform diagnostic prefix; full stream not captured')
                code = child.wait()
            finally:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                code = child.returncode
                child.stdout.close()
        require(code == 0, 'Platform compiler failed; complete bounded log retained')
        require(set(inventory(out / 'classes', '.class')) == set(lock['expected_baseline_class_names']) | {EXTRA_CLASS},
                'complete Platform class membership differs')
        require(set(inventory(out / 'generated', '.java')) == set(lock['expected_generated_source_names']),
                'actual annotation processor source membership differs')
        require(not re.search(rb'\.java:\d+: error:', raw), 'javac source errors')
        verify_all()
    except BaseException as error:
        failure = repr(error)
    post = None
    try:
        verify_all()
    except BaseException as error:
        post = repr(error)
        failure = failure or post
    receipt = {'schema': 1, 'producer': 'genuine-full-platform', 'compilerSuccess': failure is None,
               'failure': failure, 'inputPostcheckError': post, 'inputPostchecksPassed': post is None,
               'producerRecipeSha256': recipe_sha, 'producerInputsSha256': lock_sha,
               'profileId': PROFILE, 'profileSha256': args.profile_sha256, 'patchSha256': profile['patch']['sha256'],
               'sourceRevision': REVISION, 'platformSourcePostimages': {name: profile['sources'][name]['postSha256'] for name in sorted(PLATFORM_FILES)},
               'projectionReceiptSha256': args.projection_sha256, 'sourceInventory': source_inventory,
               'sourceArgumentsSha256': sha(arguments), 'bindingRoots': {name: str(path) for name, path in roots.items()},
               'classInventory': inventory(out / 'classes', '.class'), 'generatedInventory': inventory(out / 'generated', '.java'),
               'artifactClassDirectory': 'classes', 'sourceCount': len(source_paths), 'classpath': list(map(str, cp)),
               'processorpath': list(map(str, pp)), 'command': command, 'returncode': code,
               'diagnosticsSha256': sha(out / 'platform.log') if (out / 'platform.log').exists() else None,
               'displayedWarningCount': len(re.findall(rb'(?m)^warning:', raw)), 'inheritedWarningLimits': lock['inherited_javac_warnings'],
               'runtimeOrClientAcceptance': False, 'fullGradleAcceptance': False, 'privateSdkEquivalence': False,
               'freshXjcOrVersionTemplateGeneration': False, 'elapsedSeconds': time.monotonic() - started,
               'limits': limits, 'allocatedBeforeReceipt': allocated(out)}
    data = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    allocation = ((len(data) + 4095) // 4096) * 4096 + 4096
    require(allocation <= limits['receipt_reserve_bytes'], 'Platform receipt reserve exceeded')
    gate(allocation, reserve=False)
    (out / 'complete.json').write_bytes(data)
    gate(reserve=False)
    for path in out.rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    if failure:
        raise SystemExit('Full Platform compiler failed; original bounded evidence retained')
    print('Full mission-profile Platform compiled; no runtime, Client or Gradle acceptance')


if __name__ == '__main__':
    main()
