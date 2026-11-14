#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Choose CodeQL languages for a main push or the weekly schedule.

Python, Java/Kotlin, and C/C++ are not pull-request checks. A push runs a
language when a changed path belongs to it. The weekly schedule runs all three.
A change to this script or its workflow runs all three.
"""
import json
import os
from pathlib import Path
import sys
import urllib.request

LANGUAGES = ('python', 'java', 'cpp')
CPP_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'}
SELF = (
    '.github/workflows/codeql-extended.yaml',
    '.github/workflows/codeql-language.yaml',
    '.github/scripts/codeql-languages.py',
)


def push_paths():
    """GitHub path filters. `*` does not cross `/`; `**` does, including zero segments."""
    globs = ['*.py', '*.pyi', '**/*.py', '**/*.pyi']
    for prefix in ('takx', 'tests'):
        globs.append(prefix + '/*.java')
        globs.append(prefix + '/**/*.java')
    for suffix in ('.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'):
        globs.append('takx/*' + suffix)
        globs.append('takx/**/*' + suffix)
    globs.extend(SELF)
    return globs


def classify(paths):
    found = {name: False for name in LANGUAGES}
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        if path in SELF:
            return {name: True for name in LANGUAGES}
        suffix = Path(path).suffix
        if suffix in {'.py', '.pyi'}:
            found['python'] = True
        if suffix == '.java' and (path.startswith('takx/') or path.startswith('tests/')):
            found['java'] = True
        if suffix in CPP_SUFFIXES and path.startswith('takx/'):
            found['cpp'] = True
    return found


def fetch_changed(urlopen=urllib.request.urlopen):
    """Return changed paths, or None when the compare list is missing or truncated.

    GitHub's compare API returns at most 300 files. A truncated list scans every
    language rather than skipping one that fell off the page.
    """
    before = os.environ.get('BEFORE', '')
    if not before or set(before) <= {'0'}:
        return None
    url = 'https://api.github.com/repos/{}/compare/{}...{}'.format(
        os.environ['REPO'], before, os.environ['AFTER'])
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'uds-takserver-codeql',
    })
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    files = payload.get('files') or []
    if len(files) >= 300:
        return None
    return [item['filename'] for item in files if item.get('filename')]


def decide(urlopen=urllib.request.urlopen):
    if os.environ.get('EVENT_NAME') == 'schedule':
        return {name: True for name in LANGUAGES}
    if 'CHANGED' in os.environ:
        return classify(os.environ['CHANGED'].splitlines())
    changed = fetch_changed(urlopen)
    if changed is None:
        return {name: True for name in LANGUAGES}
    return classify(changed)


def emit(decision):
    lines = ''.join(f'{name}={"true" if decision[name] else "false"}\n' for name in LANGUAGES)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)


def main():
    emit(decide())


if __name__ == '__main__':
    main()
