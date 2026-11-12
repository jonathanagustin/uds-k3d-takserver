#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Conservative post-merge reuse; any absent/ambiguous evidence selects full CI."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile

REPO = 'jonathanagustin/uds-takserver'
WORKFLOW = '.github/workflows/atak-e2e.yaml'
ARTIFACT = 'atak-tested-checkout-v1'
SCHEMA = 'atak-tested-checkout-v1'
PHASES = ['stage-and-ui-import', 'android-broadcast-and-fresh-peer-observation', 'explicit-peer-return-and-android-ui-verification']
STATUS = 'ui-import-broadcast-action-fresh-challenge-and-return-verified'
# These contain producer/publisher code and tool/environment choices. Runtime
# harness changes may reuse only after their exact integrated tree was tested.
SEMANTICS = ['.github/workflows/atak-e2e.yaml', '.gitmodules', 'atak/apk', 'atak/driver', 'atak/vm', 'atak/viewer', 'atak/deploy', 'atak/zarf.yaml', 'atak/ci/device-images.sh', 'atak/ci/build-apk.sh', 'atak/ci/fetch-source.sh', 'upstream/atak-civ']


def command(args, limit=1024*1024, env=None):
    # File-backed bounded output; never print commands, responses or exceptions.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        with subprocess.Popen(args, stdout=out, stderr=err, env=env) as p:
            try:
                deadline = time.monotonic()+25
                while p.poll() is None:
                    if time.monotonic() > deadline or out.tell() > limit or err.tell() > 65536:
                        p.kill(); p.wait()
                        raise ValueError('command bound')
                    time.sleep(0.05)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
                raise ValueError('command deadline') from None
            if p.returncode or out.tell() > limit or err.tell() > 65536:
                raise ValueError('command rejected')
            out.seek(0)
            return out.read(limit+1)


def git(*args):
    return command(['git', *args]).decode().strip()


def api(path):
    return json.loads(command(['gh', 'api', 'repos/'+REPO+'/'+path]))


def keys(ref=None):
    env = os.environ.copy()
    if ref is None:
        data = command(['bash', 'atak/ci/device-images.sh', 'keys'], env=env)
    else:
        with tempfile.TemporaryDirectory() as d:
            env['GIT_INDEX_FILE'] = str(Path(d)/'index')
            command(['git', 'read-tree', ref], env=env)
            data = command(['bash', 'atak/ci/device-images.sh', 'keys'], env=env)
    result = dict(line.split('=', 1) for line in data.decode().splitlines())
    if len(result) != 11 or not all(result.values()):
        raise ValueError('invalid key inventory')
    return result


def release_current(identity, release):
    """Read manifests only. No copy/build/pull/publish/login or tag movement."""
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,3}', release):
        raise ValueError('release tag')
    def digest(ref):
        value = command(['uds', 'zarf', 'tools', 'registry', 'digest', ref], limit=256).decode().strip()
        if not re.fullmatch('sha256:[0-9a-f]{64}', value):
            raise ValueError('invalid registry digest')
        return value
    pairs = []
    for field in ['APK_IMAGE_KEYED', 'DRIVER_IMAGE_KEYED', 'VM_IMAGE_KEYED', 'VIEWER_IMAGE_KEYED']:
        ref = identity[field]
        if not re.fullmatch(r'ghcr\.io/jonathanagustin/uds-takserver/(atak-civ-apk|atak-driver|atak-civ-vm|atak-viewer):[0-9.]+-[0-9a-f]{12}', ref):
            raise ValueError('invalid image ref')
        keyed = digest(ref)  # All four keyed images must exist.
        if field != 'APK_IMAGE_KEYED':  # APK has no plain release alias.
            plain = digest(ref.rsplit(':', 1)[0]+':'+release)
            if plain != keyed:
                raise ValueError('image release stale')
        pairs.append(keyed)
    package = identity['PKG_REF']
    if not re.fullmatch(r'ghcr\.io/jonathanagustin/uds-takserver/packages/atak-device:[0-9.]+-[0-9a-f]{12}', package):
        raise ValueError('invalid package ref')
    if digest(package) != digest(package.rsplit(':', 1)[0]+':'+release):
        raise ValueError('package release stale')
    return pairs


def record(output):
    receipt = json.loads(Path('out/scenario/receipt.json').read_text())
    cleanup = json.loads(Path('out/scenario/cleanup.json').read_text())
    if receipt.get('status') != STATUS or receipt.get('passed_phases') != PHASES or cleanup.get('cleanup_verified') is not True or cleanup.get('owned_resources_absent') is not True:
        raise ValueError('scenario not qualified')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    pr = event.get('pull_request', {})
    result = {'schema': SCHEMA, 'repository': REPO, 'runId': int(os.environ['GITHUB_RUN_ID']), 'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'event': os.environ['GITHUB_EVENT_NAME'], 'pr': pr.get('number'), 'sourceHead': pr.get('head', {}).get('sha'), 'checkoutCommit': git('rev-parse', 'HEAD'), 'checkoutTree': git('rev-parse', 'HEAD^{tree}'), 'keys': keys(), 'scenarioStatus': STATUS, 'phases': PHASES, 'cleanupVerified': True}
    Path(output).write_text(json.dumps(result, sort_keys=True)+'\n')


def validate_proof(proof, run, pr, tree, identity):
    expected = {'schema': SCHEMA, 'repository': REPO, 'runId': run['id'], 'runAttempt': run['run_attempt'], 'event': 'pull_request', 'pr': pr['number'], 'sourceHead': pr['head']['sha'], 'checkoutTree': tree, 'keys': identity, 'scenarioStatus': STATUS, 'phases': PHASES, 'cleanupVerified': True}
    if any(proof.get(k) != v for k, v in expected.items()) or set(proof) != set(expected)|{'checkoutCommit'} or not re.fullmatch('[a-f0-9]{40}', proof['checkoutCommit']):
        raise ValueError('proof mismatch')


def read_artifact(run):
    listing = api(f"actions/runs/{run['id']}/artifacts?per_page=100")
    matches = [a for a in listing['artifacts'] if a['name'] == ARTIFACT]
    if listing['total_count'] > 100 or len(matches) != 1:
        raise ValueError('ambiguous proof')
    a = matches[0]
    if a['expired'] or a['size_in_bytes'] > 16384 or a.get('workflow_run', {}).get('id') != run['id']:
        raise ValueError('invalid artifact')
    raw = command(['gh', 'api', f"repos/{REPO}/actions/artifacts/{a['id']}/zip"], limit=16384)
    if a.get('digest') != 'sha256:'+hashlib.sha256(raw).hexdigest():
        raise ValueError('artifact digest mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = z.infolist()
        if len(files) != 1 or files[0].filename != 'tested-checkout.json' or files[0].file_size > 8192 or files[0].flag_bits & 1:
            raise ValueError('invalid proof archive')
        return json.loads(z.read(files[0]))


def decide(event):
    if os.environ.get('GITHUB_EVENT_NAME') != 'push' or os.environ.get('GITHUB_REF') != 'refs/heads/main' or os.environ.get('GITHUB_REPOSITORY') != REPO:
        return False
    if not os.environ.get('UDS_VERSION'):
        return False
    if event.get('forced') is not False:
        return False
    sha, before = event['after'], event['before']
    if sha != git('rev-parse', 'HEAD') or not re.fullmatch('[0-9a-f]{40}', before) or before == '0'*40:
        return False
    if git('rev-parse', 'HEAD^1') != before:
        return False
    prs = api('commits/'+sha+'/pulls?per_page=100')
    prs = [p for p in prs if p.get('merged_at') and p['merge_commit_sha'] == sha and p['base']['ref'] == 'main' and p['base']['repo']['full_name'] == REPO and p['head']['repo']['full_name'] == REPO]
    if len(prs) != 1:
        return False
    pr = prs[0]
    if git('ls-tree', '-r', before, '--', *SEMANTICS) != git('ls-tree', '-r', sha, '--', *SEMANTICS):
        return False
    identity = keys()
    if keys(before) != identity:
        return False
    listing = api('actions/workflows/atak-e2e.yaml/runs?event=pull_request&head_sha='+pr['head']['sha']+'&per_page=100')
    if listing['total_count'] > 100:
        return False
    runs = [r for r in listing['workflow_runs'] if r['head_sha'] == pr['head']['sha'] and r['event'] == 'pull_request' and r['path'] == WORKFLOW and r['repository']['full_name'] == REPO and r['head_repository']['full_name'] == REPO and any(p['number'] == pr['number'] for p in r['pull_requests'])]
    if not runs:
        return False
    run = max(runs, key=lambda r: r['id'])
    if run['status'] != 'completed' or run['conclusion'] != 'success':
        return False
    jobs = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    e2e = [j for j in jobs['jobs'] if j['name'] == 'e2e']
    if jobs['total_count'] > 100 or len(e2e) != 1 or e2e[0]['status'] != 'completed' or e2e[0]['conclusion'] != 'success':
        return False
    for name in ['Deploy UDS Core slim and TAK Server', 'ATAK device end to end', 'Record the tested checkout and scenario', 'Upload the tested checkout proof']:
        steps = [s for s in e2e[0]['steps'] if s['name'] == name]
        if len(steps) != 1 or steps[0]['status'] != 'completed' or steps[0]['conclusion'] != 'success':
            return False
    proof = read_artifact(run)
    validate_proof(proof, run, pr, git('rev-parse', 'HEAD^{tree}'), identity)
    # Resolve the actual tested checkout object through authenticated commit API;
    # run.head_sha is the PR source, not the checkout merge-tree.
    commit = api('git/commits/'+proof['checkoutCommit'])
    if commit['tree']['sha'] != proof['checkoutTree']:
        return False
    release_current(identity, os.environ['RELEASE_TAG'])
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['record', 'admit'])
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.mode == 'record':
        record(args.output)
        return
    reuse = False
    try:
        reuse = decide(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
    except (KeyError, ValueError, TypeError, AttributeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile):
        pass  # Unknown/ambiguous/error means full test, never a skipped gate.
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('reuse='+str(reuse).lower()+'\n')
    print('ATAK push admission: '+('reuse qualified exact-tree PR baseline; no publication' if reuse else 'full qualification required'))


if __name__ == '__main__':
    main()
