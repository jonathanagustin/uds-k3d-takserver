#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Publish exact reviewed historical scene bytes to an immutable prerelease."""
import argparse
import base64
import datetime
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

import publish as reel

WORKFLOW = reel.WORKFLOW
REF = reel.REF
BUNDLE = reel.BUNDLE
LIMIT = reel.LIMIT
require = reel.require
sha = reel.sha
invocation = reel.invocation
SCENES = {
    'create-map-marker': ('Create a map marker', 43.5, 6, 180),
    'share-feature': ('Share a feature', 58, 6.5, 195),
    'shared-marker': ('Shared marker', 74, 6, 180),
}
SUBJECTS = {slug + ext for slug in SCENES for ext in ('.mp4', '.json')}
FILES = SUBJECTS | {slug + '.jpg' for slug in SCENES} | {BUNDLE, 'Inter-LICENSE.txt'}
LICENSE_SHA = '262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a'


def decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def source_identity(gh, repo, run_id, attempt):
    require(re.fullmatch(r'[1-9][0-9]{0,19}', str(run_id)) and
            re.fullmatch(r'[1-9][0-9]{0,9}', str(attempt)), 'invalid source run/attempt')
    repository, run = reel.run_identity(gh, repo, str(run_id))
    require(run['run_attempt'] == int(attempt), 'source attempt mismatch')
    return repository, run


def artifact_bytes(gh, repo, repository, run):
    pages = gh.run('api', '--paginate', '--slurp',
                   f"repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
    found = [a for page in pages for a in page['artifacts'] if a['name'] == 'ui-scene-previews']
    require(len(found) == 1 and found[0]['expired'] is False, 'expected one unexpired scene artifact')
    artifact = found[0]
    expected = {'id': run['id'], 'repository_id': repository['id'],
                'head_repository_id': repository['id'], 'head_branch': 'main', 'head_sha': run['head_sha']}
    require(all(artifact['workflow_run'].get(k) == v for k, v in expected.items()), 'artifact source mismatch')
    require(type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= LIMIT,
            'artifact size exceeds bound')
    data = gh.run('api', f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
    require(len(data) == artifact['size_in_bytes'] and artifact['digest'] == 'sha256:' + sha(data),
            'archive digest/size mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == 11 and {e.filename for e in entries} == FILES, 'expected exact eleven scene files')
        require(all(not e.is_dir() and not stat.S_ISLNK(e.external_attr >> 16)
                    and stat.S_IFMT(e.external_attr >> 16) in (0, stat.S_IFREG)
                    and 0 < e.file_size <= LIMIT for e in entries)
                and sum(e.file_size for e in entries) <= LIMIT, 'unsafe archive member')
        return {e.filename: archive.read(e) for e in entries}


def source_file(gh, repo, run, path):
    value = gh.api(f"repos/{repo}/contents/{path}?ref={run['head_sha']}")
    require(value['type'] == 'file' and value['encoding'] == 'base64'
            and type(value['size']) is int and 0 < value['size'] <= 1024 * 1024, 'invalid source file')
    data = base64.b64decode(value['content'], validate=False)
    require(len(data) == value['size'], 'source file size mismatch')
    return data


def verify_manifests(files, recipe, lock_bytes):
    require(set(files) == FILES, 'unexpected file inventory')
    require(sha(files['Inter-LICENSE.txt']) == LICENSE_SHA, 'font license mismatch')
    lock = decode(lock_bytes)
    source = next(s for s in lock['sources'] if s['file'] == 'demo-clip-sync.mp4')
    required = {'purpose', 'source_input', 'font_input', 'recipe_sha256', 'lock_sha256',
                'tool_versions', 'scene', 'outputs', 'probe', 'acceptance'}
    for slug, (label, start, duration, frames) in SCENES.items():
        value = decode(files[slug + '.json'])
        require(set(value) in (required, required | {'branding_input'}), 'scene manifest schema mismatch')
        require(isinstance(value['tool_versions'], dict) and set(value['tool_versions']) == {'ffmpeg', 'ffprobe'}
                and all(isinstance(v, str) and 0 < len(v) <= 4096 for v in value['tool_versions'].values()),
                'missing producer tool versions')
        if 'branding_input' in value:
            require(set(value['branding_input']) == {'file', 'sha256'}
                    and value['branding_input']['file'] == 'assets/tak-on-uds-dark.svg'
                    and re.fullmatch(r'[0-9a-f]{64}', value['branding_input']['sha256']), 'invalid branding input')
        require(value['purpose'] == lock['description'] and value['source_input'] == source
                and value['font_input'] == lock['font'], 'locked source/font mismatch')
        require(value['recipe_sha256'] == sha(recipe) and value['lock_sha256'] == sha(lock_bytes),
                'source recipe/lock mismatch')
        require(value['scene'] == {'label': label, 'source': source['file'], 'start_seconds': start,
                                 'duration_seconds': duration}, 'scene timing mismatch')
        require(value['acceptance'] == 'Historical footage edit only; no new deployment, TAKX, or live interoperability acceptance',
                'historical acceptance label mismatch')
        outputs = value['outputs']
        require(len(outputs) == 2 and {v['file'] for v in outputs} == {slug + '.mp4', slug + '.jpg'},
                'scene output inventory mismatch')
        for item in outputs:
            data = files[item['file']]
            require(set(item) == {'file', 'sha256', 'bytes'} and type(item['bytes']) is int
                    and item['bytes'] == len(data) and item['sha256'] == sha(data), 'scene output mismatch')
        probe = value['probe']
        require(len(probe['streams']) == 1 and probe['streams'][0]['codec_type'] == 'video'
                and probe['streams'][0]['codec_name'] == 'h264'
                and (probe['streams'][0]['width'], probe['streams'][0]['height']) == (1920, 1080)
                and float(probe['format']['duration']) == duration, 'unexpected scene media description')


def verify_review(review, files, run):
    require(set(review) == {'schema', 'source_run_id', 'source_attempt', 'source_commit',
                           'reviewer', 'reviewed_at', 'full_frame_privacy_review', 'frames', 'sha256'},
            'review schema mismatch')
    require(review['schema'] == 1 and type(review['schema']) is int
            and review['source_run_id'] == run['id'] and type(review['source_run_id']) is int
            and review['source_attempt'] == run['run_attempt'] and type(review['source_attempt']) is int
            and review['source_commit'] == run['head_sha'], 'review source mismatch')
    require(review['full_frame_privacy_review'] is True, 'complete privacy review required')
    require(isinstance(review['reviewer'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', review['reviewer']),
            'reviewer handle required')
    reviewed = datetime.datetime.strptime(review['reviewed_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    require(reviewed <= datetime.datetime.now(datetime.timezone.utc), 'review date is in the future')
    require(review['frames'] == {s + '.mp4': v[3] for s, v in SCENES.items()}
            and all(type(n) is int for n in review['frames'].values()), 'review must cover all 555 frames')
    require(review['sha256'] == {name: sha(data) for name, data in files.items()}, 'review asset hashes mismatch')

def verify_statement(statement, files, repo, repository, run):
    require(statement["_type"] == "https://in-toto.io/Statement/v1"
            and statement["predicateType"] == "https://slsa.dev/provenance/v1",
            "unexpected attestation type")
    subjects = statement["subject"]
    expected = {name: {"sha256": sha(files[name])} for name in SUBJECTS}
    require(len(subjects) == len(SUBJECTS) and {s["name"]: s["digest"] for s in subjects} == expected,
            "signed subject inventory/digest mismatch")
    definition = statement["predicate"]["buildDefinition"]
    require(definition["buildType"] == "https://actions.github.io/buildtypes/workflow/v1",
            "unexpected attested build type")
    require(definition["externalParameters"]["workflow"] == {
        "ref": REF, "repository": f"https://github.com/{repo}", "path": WORKFLOW},
        "signed workflow identity mismatch")
    github = definition["internalParameters"]["github"]
    require(github["event_name"] == "workflow_dispatch"
            and github["repository_id"] == str(repository["id"])
            and github["repository_owner_id"] == str(repository["owner"]["id"]),
            "signed repository/owner/event mismatch")
    require(definition["resolvedDependencies"] == [{
        "uri": f"git+https://github.com/{repo}@{REF}",
        "digest": {"gitCommit": run["head_sha"]}}], "signed source commit/ref mismatch")
    details = statement["predicate"]["runDetails"]
    require(details["builder"]["id"] == f"https://github.com/{repo}/{WORKFLOW}@{REF}",
            "signed builder mismatch")
    require(details["metadata"]["invocationId"] == invocation(repo, run),
            "signed invocation does not match the source run attempt")


def verify_attestations(gh, directory, files, repo, repository, run):
    for name in sorted(SUBJECTS):
        results = gh.run("attestation", "verify", str(directory / name),
                         "--bundle", str(directory / BUNDLE), "--repo", repo,
                         "--signer-workflow", f"{repo}/{WORKFLOW}",
                         "--signer-digest", run["head_sha"], "--source-digest", run["head_sha"],
                         "--source-ref", REF, "--cert-oidc-issuer",
                         "https://token.actions.githubusercontent.com", "--predicate-type",
                         "https://slsa.dev/provenance/v1", "--format", "json")
        require(len(results) == 1, "expected one verified attestation per subject")
        # Only use the cryptographically verified result, never an unverified
        # decode of the bundle's DSSE payload.
        verify_statement(results[0]["verificationResult"]["statement"], files,
                         repo, repository, run)


def inspect_media(directory):
    for slug, (_, _, duration, frames) in SCENES.items():
        result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                 '-show_format', '-of', 'json', str(directory / (slug + '.mp4'))],
                                check=True, capture_output=True, timeout=30)
        require(len(result.stdout) <= 1024 * 1024, 'media probe exceeds bound')
        value = json.loads(result.stdout)
        require(len(value['streams']) == 1, 'scene must have one video stream and no audio')
        stream = value['streams'][0]
        require(stream['codec_type'] == 'video' and stream['codec_name'] == 'h264'
                and (stream['width'], stream['height']) == (1920, 1080)
                and stream['avg_frame_rate'] == '30/1' and stream['nb_read_frames'] == str(frames)
                and float(value['format']['duration']) == duration, 'actual media shape mismatch')


def matching_assets(gh, repo, release_id, files):
    pages = gh.run('api', '--paginate', '--slurp', f'repos/{repo}/releases/{release_id}/assets?per_page=100')
    found = {}
    for asset in (a for page in pages for a in page):
        name = asset['name']
        require(name in FILES and name not in found and asset['state'] == 'uploaded'
                and asset['size'] == len(files[name]) and asset.get('digest') == 'sha256:' + sha(files[name]),
                'release asset collision or unverifiable asset')
        found[name] = asset['id']
    return found


def check_release(value, tag, run, body):
    require(type(value['id']) is int and value['id'] > 0 and value['tag_name'] == tag
            and type(value['draft']) is bool and value['prerelease'] is True
            and value['target_commitish'] == run['head_sha'] and value['body'] == body,
            'release identity or review description mismatch')


def check_tag(gh, repo, tag, run):
    value = gh.api(f'repos/{repo}/git/ref/tags/{tag}')
    require(value['object'] == {'type': 'commit', 'sha': run['head_sha'],
                              'url': f"https://api.github.com/repos/{repo}/git/commits/{run['head_sha']}"},
            'tag identity mismatch')
    return value['object']


def publish(gh, repo, run_id, attempt, ref, review):
    require(ref == REF and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'main repository dispatch required')
    repository, run = source_identity(gh, repo, run_id, attempt)
    files = artifact_bytes(gh, repo, repository, run)
    recipe = source_file(gh, repo, run, 'demo/ui-reel/render.py')
    lock = source_file(gh, repo, run, 'demo/ui-reel/inputs.lock.json')
    verify_manifests(files, recipe, lock)
    verify_review(review, files, run)
    tag = f"ui-scenes-run-{run['id']}-attempt-{run['run_attempt']}"
    body = (f"Historical UI scene edits; not a new capture, current branding, TAKX, SSO, Grafana or Portal evidence.\n"
            f"Source {invocation(repo, run)} at {run['head_sha']}.\n"
            f"All 555 frames reviewed by @{review['reviewer']} on {review['reviewed_at']}.\n"
            "Original signed scene files retained without rerendering. Not a package release.")
    with tempfile.TemporaryDirectory(prefix='ui-scenes-publish-') as temporary:
        directory = Path(temporary)
        for name, data in files.items():
            (directory / name).write_bytes(data)
        inspect_media(directory)
        verify_attestations(gh, directory, files, repo, repository, run)
        require(reel.identity_fingerprint(*source_identity(gh, repo, run_id, attempt))
                == reel.identity_fingerprint(repository, run), 'source changed during verification')
        pages = gh.run('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100')
        matches = [r for page in pages for r in page if r['tag_name'] == tag]
        require(len(matches) <= 1, 'duplicate target release')
        if matches:
            target = gh.api(f"repos/{repo}/releases/{matches[0]['id']}")
        else:
            refs = gh.api(f'repos/{repo}/git/matching-refs/tags/{tag}')
            refs = [r for r in refs if r['ref'] == 'refs/tags/' + tag]
            require(len(refs) <= 1, 'duplicate target tag')
            if refs:
                check_tag(gh, repo, tag, run)
            else:
                gh.run('api', '--method', 'POST', f'repos/{repo}/git/refs',
                       '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + run['head_sha'])
            target = gh.run('api', '--method', 'POST', f'repos/{repo}/releases',
                            '-f', 'tag_name=' + tag, '-f', 'target_commitish=' + run['head_sha'],
                            '-F', 'draft=true', '-F', 'prerelease=true', '-f', 'make_latest=false',
                            '-f', 'name=Historical UI scenes ' + str(run_id) + ' attempt ' + str(attempt),
                            '-f', 'body=' + body)
        check_release(target, tag, run, body)
        tag_object = check_tag(gh, repo, tag, run)
        present = matching_assets(gh, repo, target['id'], files)
        if not target['draft']:
            require(set(present) == FILES, 'published target is incomplete; never edit public release')
        else:
            for name in sorted(FILES - set(present)):
                require((directory / name).read_bytes() == files[name], 'staged bytes changed')
                check_tag(gh, repo, tag, run)
                current = gh.api(f"repos/{repo}/releases/{target['id']}")
                check_release(current, tag, run, body)
                require(current['draft'] is True, 'target changed before upload')
                gh.run('release', 'upload', tag, str(directory / name), '--repo', repo, binary=True)
                require(name in matching_assets(gh, repo, target['id'], files), 'upload not confirmed')
        present = matching_assets(gh, repo, target['id'], files)
        require(set(present) == FILES, 'incomplete scene release')
        # API digests alone are insufficient: hash every downloaded immutable asset ID.
        for name, asset_id in present.items():
            data = gh.run('api', f'repos/{repo}/releases/assets/{asset_id}',
                          '-H', 'Accept: application/octet-stream', binary=True)
            require(data == files[name], 'release readback bytes mismatch')
        require(reel.identity_fingerprint(*source_identity(gh, repo, run_id, attempt))
                == reel.identity_fingerprint(repository, run), 'source changed before promotion')
        require(check_tag(gh, repo, tag, run) == tag_object, 'tag changed before promotion')
        current = gh.api(f"repos/{repo}/releases/{target['id']}")
        check_release(current, tag, run, body)
        require(current['draft'] == target['draft'], 'release state changed')
        if current['draft']:
            gh.run('api', '--method', 'PATCH', f"repos/{repo}/releases/{target['id']}",
                   '-F', 'draft=false', '-f', 'make_latest=false')
            final = gh.api(f"repos/{repo}/releases/{target['id']}")
            check_release(final, tag, run, body)
            require(final['draft'] is False, 'release not promoted')
            require(check_tag(gh, repo, tag, run) == tag_object, 'tag changed after promotion')
    print(f'Verified immutable historical scene release: {tag}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run-id', default=os.environ.get('SCENE_SOURCE_RUN_ID', ''))
    parser.add_argument('--source-attempt', default=os.environ.get('SCENE_SOURCE_ATTEMPT', ''))
    parser.add_argument('--mode-only', action='store_true')
    args = parser.parse_args()
    try:
        require(re.fullmatch(r'[1-9][0-9]{0,19}', args.source_run_id)
                and re.fullmatch(r'[1-9][0-9]{0,9}', args.source_attempt), 'invalid source run/attempt')
        if args.mode_only:
            require(os.environ.get('GITHUB_REF') == REF and not os.environ.get('RELEASE_TAG')
                    and not os.environ.get('SOURCE_RUN_ID') and os.environ.get('EXPORT_SCENES') != 'true',
                    'scene publication cannot mix render or reel publication inputs')
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('mode=scenes\n')
            return
        # Reviews must be committed in the publisher checkout, never supplied by an artifact.
        path = f'demo/ui-reel/reviews/{args.source_run_id}-{args.source_attempt}.json'
        result = subprocess.run(['git', 'show', 'HEAD:' + path], check=True, capture_output=True, timeout=10)
        require(len(result.stdout) <= 32768, 'review record exceeds bound')
        review = decode(result.stdout)
        publish(reel.GitHub(), os.environ['GITHUB_REPOSITORY'], args.source_run_id,
                args.source_attempt, os.environ['GITHUB_REF'], review)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        raise SystemExit(f'Scene publication refused ({type(error).__name__}); complete committed privacy review and valid source evidence required.') from None


if __name__ == '__main__':
    main()
