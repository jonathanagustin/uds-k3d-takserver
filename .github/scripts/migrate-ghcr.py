#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Copy legacy OCI artifacts without rebuilding, overwriting or deleting them."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OWNER = 'jonathanagustin'
OLD = OWNER + '/uds-k3d-takserver/'
NEW = OWNER + '/uds-takserver/'
FAMILIES = ['takserver', 'takserver-api', 'takserver-messaging', 'takserver-config',
            'takserver-plugins', 'takserver-database-setup', 'takserver-ignite',
            'cloudtak', 'postgis', 'atak-civ-apk', 'atak-civ-vm', 'atak-viewer', 'atak-driver',
            'packages/atak-device', 'checkpoints/k3d-core-slim-dev',
            'ci-packages/takserver', 'build-cache']
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
TAG = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z')
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json',
                    'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json',
                    'application/vnd.docker.distribution.manifest.v2+json'])


class MigrationError(RuntimeError):
    pass


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        result = super().redirect_request(request, fp, code, message, headers, url)
        if result and urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(request.full_url).netloc:
            result.remove_header('Authorization')
        return result


class Registry:
    def __init__(self, base='https://ghcr.io'):
        if base != 'https://ghcr.io' and not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', base):
            raise MigrationError('Only GHCR or a loopback test registry is permitted')
        self.base = base
        self.host = urllib.parse.urlsplit(base).netloc
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.tokens = {}
        self.manifests = {}
        self.checked_blobs = {}

    def token(self, repository):
        if self.host != 'ghcr.io':
            return None
        existing = self.tokens.get(repository)
        if existing and existing[0] > time.monotonic():
            return existing[1]
        query = urllib.parse.urlencode({'service': 'ghcr.io', 'scope': 'repository:' + repository + ':pull'})
        try:
            with self.opener.open(self.base + '/token?' + query, timeout=30) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise MigrationError('Registry token request failed: HTTP ' + str(error.code)) from None
        token = body.get('token') or body.get('access_token')
        if not token:
            raise MigrationError('Registry returned no pull token')
        self.tokens[repository] = (time.monotonic() + 120, token)
        return token

    def request(self, repository, path, head=False, missing=False):
        for attempt in range(4):
            headers = {'Accept': ACCEPT}
            token = self.token(repository)
            if token:
                headers['Authorization'] = 'Bearer ' + token
            request = urllib.request.Request(self.base + '/v2/' + repository + '/' + path,
                                             headers=headers, method='HEAD' if head else 'GET')
            try:
                with self.opener.open(request, timeout=45) as response:
                    return response.headers, b'' if head else response.read()
            except urllib.error.HTTPError as error:
                if missing and error.code == 404:
                    return None
                if error.code == 401 and attempt == 0:
                    self.tokens.pop(repository, None)
                    continue
                if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise MigrationError('Registry request failed for ' + repository + ': HTTP ' + str(error.code)) from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise MigrationError('Registry transport failed for ' + repository) from None
                time.sleep(2 ** attempt)
        raise MigrationError('Registry request did not complete')

    def tags(self, repository):
        tags, path, seen = [], 'tags/list?n=100', set()
        while path:
            if path in seen or len(seen) > 100:
                raise MigrationError('Invalid tag pagination')
            seen.add(path)
            headers, raw = self.request(repository, path)
            tags.extend(json.loads(raw).get('tags') or [])
            link = headers.get('Link', '')
            path = None
            if link:
                match = re.fullmatch(r'<([^>]+)>;\s*rel="next"', link)
                if not match:
                    raise MigrationError('Unexpected registry pagination link')
                url = urllib.parse.urlsplit(urllib.parse.urljoin(self.base, match[1]))
                prefix = '/v2/' + repository + '/'
                if url.netloc != self.host or not url.path.startswith(prefix):
                    raise MigrationError('Registry pagination escaped repository')
                path = url.path[len(prefix):] + ('?' + url.query if url.query else '')
        if len(tags) != len(set(tags)) or any(not TAG.fullmatch(tag) for tag in tags):
            raise MigrationError('Invalid or duplicate registry tags')
        return sorted(tags)

    def manifest(self, repository, reference, missing=False):
        result = self.request(repository, 'manifests/' + reference, missing=missing)
        if result is None:
            return None
        headers, raw = result
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if headers.get('Docker-Content-Digest') != digest or (DIGEST.fullmatch(reference) and reference != digest):
            raise MigrationError('Manifest byte digest mismatch')
        self.manifests[repository, digest] = json.loads(raw)
        return digest

    def closure(self, repository, root):
        manifests, blobs, pending = set(), {}, [root]
        while pending:
            digest = pending.pop()
            if digest in manifests:
                continue
            if (repository, digest) not in self.manifests:
                self.manifest(repository, digest)
            body = self.manifests[repository, digest]
            manifests.add(digest)
            descriptors = [(item, True) for item in body.get('manifests', [])]
            descriptors += [(item, False) for item in body.get('layers', []) + body.get('blobs', [])]
            if body.get('config'):
                descriptors.append((body['config'], False))
            if body.get('subject'):
                descriptors.append((body['subject'], True))
            for item, is_manifest in descriptors:
                child, size = item.get('digest'), item.get('size')
                if not isinstance(child, str) or not DIGEST.fullmatch(child) or not isinstance(size, int) or size < 0:
                    raise MigrationError('Invalid OCI descriptor')
                if is_manifest and ('manifest' in item.get('mediaType', '') or 'index' in item.get('mediaType', '')):
                    pending.append(child)
                else:
                    blobs[child] = size
        for digest, size in blobs.items():
            previous = self.checked_blobs.get((repository, digest))
            if previous is not None:
                if previous != size:
                    raise MigrationError('Inconsistent blob descriptor size')
                continue
            headers, _ = self.request(repository, 'blobs/' + digest, head=True)
            if int(headers.get('Content-Length', '-1')) != size:
                raise MigrationError('Blob size mismatch')
            if headers.get('Docker-Content-Digest', digest) != digest:
                raise MigrationError('Blob digest header mismatch')
            self.checked_blobs[repository, digest] = size
        return {'manifests': sorted(manifests), 'blobs': blobs}


def plan_family(registry, family):
    source, destination = OLD + family, NEW + family
    entries = []
    for tag in registry.tags(source):
        digest = registry.manifest(source, tag)
        existing = registry.manifest(destination, tag, missing=True)
        if tag.startswith('sha256-') and existing not in (None, digest):
            raise MigrationError('Conflicting signature/referrer tag requires explicit merge review')
        target = tag if existing in (None, digest) else 'legacy-' + digest.split(':')[1]
        target_digest = existing if target == tag else registry.manifest(destination, target, missing=True)
        if target_digest not in (None, digest):
            raise MigrationError('Legacy digest alias collision')
        entries.append({'source_tag': tag, 'digest': digest, 'destination_tag': target,
                        'preserved_destination_digest': existing if target != tag else None,
                        'already_present': target_digest == digest})
    if not entries:
        raise MigrationError('Expected legacy repository has no tags: ' + family)
    return {'family': family, 'source': source, 'destination': destination, 'entries': entries}


def validate_plan(plan):
    if plan.get('schema') != 1 or not plan.get('families'):
        raise MigrationError('Unknown or empty migration plan')
    seen = set()
    for family in plan['families']:
        name = family['family']
        if name not in FAMILIES or name in seen or family['source'] != OLD + name or family['destination'] != NEW + name:
            raise MigrationError('Plan escaped the authorized namespace')
        seen.add(name)
        if not family['entries']:
            raise MigrationError('Empty family inventory')
        for entry in family['entries']:
            if not TAG.fullmatch(entry['source_tag']) or not TAG.fullmatch(entry['destination_tag']) or not DIGEST.fullmatch(entry['digest']):
                raise MigrationError('Invalid tag or digest in plan')
            preserved = entry['preserved_destination_digest']
            expected = entry['source_tag'] if preserved is None else 'legacy-' + entry['digest'].split(':')[1]
            if entry['destination_tag'] != expected or (preserved is not None and not DIGEST.fullmatch(preserved)):
                raise MigrationError('Invalid conflict preservation plan')
            if preserved and entry['source_tag'].startswith('sha256-'):
                raise MigrationError('Signature/referrer tags cannot be moved to undiscoverable aliases')


def copy_family(family, receipt_dir):
    registry = Registry()
    completed = []
    copied = set()
    for entry in family['entries']:
        source, destination = family['source'], family['destination']
        digest, tag = entry['digest'], entry['destination_tag']
        if registry.manifest(source, entry['source_tag']) != digest:
            raise MigrationError('Source tag changed after inventory')
        existing = registry.manifest(destination, tag, missing=True)
        if existing not in (None, digest):
            raise MigrationError('Destination tag changed after inventory')
        if existing is None:
            # Copies the complete index, all architectures and referenced blobs.
            command = ['uds', 'zarf', 'tools', 'registry', 'copy', '--no-clobber', '--jobs', '2',
                       registry.host + '/' + source + '@' + digest,
                       registry.host + '/' + destination + ':' + tag]
            result = subprocess.run(command, text=True, capture_output=True, timeout=900)
            if result.returncode:
                raise MigrationError('Registry copy failed for ' + family['family'] + ':' + tag)
        if registry.manifest(destination, tag) != digest:
            raise MigrationError('Copied manifest differs from source')
        if digest not in copied:
            before = registry.closure(source, digest)
            after = registry.closure(destination, digest)
            if before != after:
                raise MigrationError('Copied OCI graph differs from source')
            copied.add(digest)
        preserved = entry['preserved_destination_digest']
        if preserved and registry.manifest(destination, entry['source_tag']) != preserved:
            raise MigrationError('Current destination alias changed')
        completed.append(entry)
        partial = {'schema': 1, 'family': family['family'], 'entries': completed,
                   'verified_unique_graphs': len(copied),
                   'verification': 'manifest byte digests and anonymous blob availability/size'}
        path = receipt_dir / (family['family'].replace('/', '_') + '.json')
        path.write_text(json.dumps(partial, indent=2) + '\n')
        print(family['family'] + ':' + entry['source_tag'] + ' -> ' + tag, flush=True)
    return {'family': family['family'], 'tags': len(completed), 'unique_graphs': len(copied)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'copy'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--receipts', type=Path)
    parser.add_argument('--family', action='append', choices=FAMILIES)
    args = parser.parse_args()
    if args.mode == 'plan':
        families = args.family or FAMILIES
        results = []
        for family in families:
            print('Inventory: ' + family, flush=True)
            results.append(plan_family(Registry(), family))
        plan = {'schema': 1, 'families': results, 'policy': 'copy only; retain current aliases; no deletion'}
        validate_plan(plan)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open('x') as output:
            json.dump(plan, output, indent=2)
            output.write('\n')
    else:
        plan = json.loads(args.plan.read_text())
        validate_plan(plan)
        if not args.receipts:
            parser.error('--receipts is required for copying')
        args.receipts.mkdir(parents=True, exist_ok=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda family: copy_family(family, args.receipts), plan['families']))
        (args.receipts / 'complete.json').write_text(json.dumps({'schema': 1, 'families': results,
            'plan_sha256': hashlib.sha256(args.plan.read_bytes()).hexdigest(), 'deleted': False}, indent=2) + '\n')


if __name__ == '__main__':
    try:
        main()
    except (MigrationError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error) if isinstance(error, MigrationError) else 'Registry command timed out') from None
