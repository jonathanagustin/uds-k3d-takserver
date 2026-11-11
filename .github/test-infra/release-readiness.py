#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Publish one source-bound draft only after the workflow's verified outputs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import urllib.error

REPO = 'jonathanagustin/uds-takserver'
BASE = 'https://api.github.com/repos/' + REPO
SHA = re.compile(r'[0-9a-f]{40}')
TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+')


def require(value):
    if not value:
        raise ValueError('release readiness identity check failed')


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('release API redirect refused')


def http_metadata(error):
    """Classify bounded error data; never retain upstream text in diagnostics."""
    result = {'reason': 'unknown', 'remaining': 'unknown', 'reset': 'unknown',
              'accepted_contents': 'unknown'}
    headers = error.headers
    if headers is not None:
        for name, key in [('X-RateLimit-Remaining', 'remaining'), ('X-RateLimit-Reset', 'reset')]:
            value = headers.get(name)
            if isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value):
                result[key] = int(value)
        value = headers.get('X-Accepted-GitHub-Permissions')
        if isinstance(value, str) and len(value) <= 1024:
            parts = [part.strip() for part in value.split(',')]
            if parts and all(re.fullmatch(r'[a-z_]+=(?:read|write|admin)', part) for part in parts):
                contents = [part.split('=')[1] for part in parts if part.startswith('contents=')]
                if len(contents) == 1 and contents[0] in ('read', 'write'):
                    result['accepted_contents'] = contents[0]
    try:
        raw = error.read(4097)
        if len(raw) > 4096:
            return result
        payload = json.loads(raw, object_pairs_hook=unique)
        message = payload.get('message') if isinstance(payload, dict) else None
        if message in ('Resource not accessible by integration', 'Resource not accessible by personal access token'):
            result['reason'] = 'access-denied'
        elif isinstance(message, str) and re.match(r'^API rate limit exceeded(?:[ .]|$)', message):
            result['reason'] = 'primary-rate-limit'
        elif isinstance(message, str) and message.startswith('You have exceeded a secondary rate limit.'):
            result['reason'] = 'secondary-rate-limit'
        elif message == 'Bad credentials':
            result['reason'] = 'bad-credentials'
    except (ValueError, UnicodeError, OSError, RecursionError):
        pass
    return result


class APIFailure(ValueError):
    """Carry only fixed diagnostic metadata, never upstream exception text."""
    def __init__(self, operation, kind, status=None, metadata=None):
        require(operation in ('release-id', 'release-tag', 'git-ref', 'git-tag'))
        require(kind in ('HTTP', 'transport', 'timeout'))
        self.operation = operation
        self.kind = kind
        self.status = status if type(status) is int and 100 <= status <= 599 else 'unknown'
        self.metadata = metadata or {'reason': 'unknown', 'remaining': 'unknown', 'reset': 'unknown',
                                     'accepted_contents': 'unknown'}
        super().__init__('release API failure')


class API:
    def __init__(self, token):
        require(bool(token))
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, path, payload=None):
        require(bool(re.fullmatch(r'/releases/(?:tags/v[0-9]+\.[0-9]+\.[0-9]+|[1-9][0-9]*)'
                                 r'|/git/ref/tags/v[0-9]+\.[0-9]+\.[0-9]+'
                                 r'|/git/tags/[0-9a-f]{40}', path)))
        if payload is not None:
            require(bool(re.fullmatch(r'/releases/[1-9][0-9]*', path)) and payload == {'draft': False})
        operation = ('release-tag' if path.startswith('/releases/tags/') else
                     'release-id' if path.startswith('/releases/') else
                     'git-ref' if path.startswith('/git/ref/') else 'git-tag')
        request = urllib.request.Request(BASE + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method='PATCH' if payload is not None else 'GET',
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise APIFailure(operation, 'HTTP', response.status)
                data = response.read(262145)
                require(len(data) <= 262144)
        except urllib.error.HTTPError as exc:
            # HTTPError owns a response stream. Close it before discarding the
            # exception so deferred cleanup cannot warn with its private reason.
            try:
                metadata = http_metadata(exc)
            finally:
                exc.close()
            raise APIFailure(operation, 'HTTP', exc.code, metadata) from None
        except TimeoutError:
            raise APIFailure(operation, 'timeout') from None
        except urllib.error.URLError as exc:
            kind = 'timeout' if isinstance(exc.reason, TimeoutError) else 'transport'
            raise APIFailure(operation, kind) from None
        except OSError:
            raise APIFailure(operation, 'transport') from None
        result = json.loads(data, object_pairs_hook=unique)
        require(isinstance(result, dict))
        return result


def source_at_tag(api, tag):
    record = api('/git/ref/tags/' + tag)
    require(record.get('ref') == 'refs/tags/' + tag)
    obj = record['object']
    seen = set()
    for _ in range(5):
        require(isinstance(obj, dict) and bool(SHA.fullmatch(obj.get('sha', ''))))
        if obj.get('type') == 'commit':
            return obj['sha']
        require(obj.get('type') == 'tag' and obj['sha'] not in seen)
        seen.add(obj['sha'])
        record = api('/git/tags/' + obj['sha'])
        require(record.get('sha') == obj['sha'])
        obj = record['object']
    raise ValueError('tag chain refused')


def validate(record, tag, release_id, source, *, public=None):
    require(type(record.get('id')) is int and record['id'] > 0)
    require(record.get('url') == BASE + '/releases/' + str(record['id']))
    require(record.get('tag_name') == tag and record.get('prerelease') is False)
    require(type(record.get('draft')) is bool)
    if release_id:
        # target_commitish is ignored for existing tags; only the peeled Git
        # object, not this mutable release metadata, establishes commit identity.
        require(str(record['id']) == release_id)
    if public is not None:
        require(record['draft'] is not public)


def check_release(api, tag, release_id='', source='', checked_source=''):
    require(bool(TAG.fullmatch(tag)))
    require((release_id == '' and source == '') or
            (bool(re.fullmatch(r'[1-9][0-9]*', release_id)) and bool(SHA.fullmatch(source))))
    # The tag endpoint exposes published releases; a bound draft must be read
    # by its exact supplied ID. Validation below still binds tag and Git source.
    record = api('/releases/' + release_id if release_id else '/releases/tags/' + tag)
    validate(record, tag, release_id, source)
    actual = source_at_tag(api, tag)
    if source:
        require(actual == source)
    if checked_source:
        require(bool(SHA.fullmatch(checked_source)) and actual == checked_source)
    if record['draft']:
        require(bool(release_id) and actual == source)
    return record


def promote(api, tag, release_id='', source=''):
    record = check_release(api, tag, release_id, source)
    if record['draft'] is False:
        return 'already-public'
    # Re-read exact ID immediately before mutation; no lookup-dependent PATCH.
    path = '/releases/' + release_id
    current = api(path)
    validate(current, tag, release_id, source, public=False)
    require(source_at_tag(api, tag) == source)
    updated = api(path, {'draft': False})
    validate(updated, tag, release_id, source, public=True)
    final = api(path)
    validate(final, tag, release_id, source, public=True)
    require(source_at_tag(api, tag) == source)
    return 'published'


def main():
    try:
        require(os.environ.get('GITHUB_REPOSITORY') == REPO)
        workflow_sha = os.environ.get('WORKFLOW_SHA', '')
        require(bool(SHA.fullmatch(workflow_sha)))
        root = Path(__file__).resolve().parents[2]
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, timeout=10).decode().strip()
        require(actual == workflow_sha)
        event, ref = os.environ.get('GITHUB_EVENT_NAME'), os.environ.get('GITHUB_REF')
        require(event in ('push', 'release', 'workflow_dispatch'))
        if os.environ.get('RELEASE_ID') or os.environ.get('RELEASE_SOURCE_SHA'):
            require(event in ('push', 'workflow_dispatch') and ref == 'refs/heads/main')
        api = API(os.environ.get('GH_TOKEN', ''))
        args = (api, os.environ.get('RELEASE_TAG', ''), os.environ.get('RELEASE_ID', ''),
                os.environ.get('RELEASE_SOURCE_SHA', ''))
        mode = os.environ.get('READINESS_MODE', 'promote')
        require(mode in ('check', 'promote'))
        if mode == 'check':
            checked = os.environ.get('CHECKED_SOURCE_SHA', '')
            require(bool(SHA.fullmatch(checked)))
            check_release(*args, checked_source=checked)
            outcome = 'source-verified'
        else:
            outcome = promote(*args)
        print('Release readiness: ' + outcome)
        return 0
    except APIFailure as exc:
        print(f'Release readiness API failure: operation={exc.operation} status={exc.status} kind={exc.kind}'
              f" reason={exc.metadata['reason']} remaining={exc.metadata['remaining']}"
              f" reset={exc.metadata['reset']} accepted_contents={exc.metadata['accepted_contents']}",
              file=sys.stderr)
        return 1
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OSError, subprocess.SubprocessError):
        print('Release readiness verification failed; no success inferred', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
