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
        request = urllib.request.Request(BASE + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method='PATCH' if payload is not None else 'GET',
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=20) as response:
            require(response.status == 200)
            data = response.read(262145)
            require(len(data) <= 262144)
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
    record = api('/releases/tags/' + tag)
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
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OSError, subprocess.SubprocessError):
        print('Release readiness verification failed; no success inferred', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
