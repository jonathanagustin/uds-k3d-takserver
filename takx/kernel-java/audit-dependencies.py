#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Query OSV for the exact direct Maven coordinates in both compiler profiles."""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('kernel_recipe', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scope', choices=('engine', 'engine-shared'), default='engine')
args = parser.parse_args()
lock = json.loads((HERE / 'inputs.lock.json').read_text())
profiles = {}
for profile in ('baseline', 'patched'):
    selected = BUILD.select_profile(lock, profile, args.scope)
    queries = []
    for entry in selected['public_jars'].values():
        path = urllib.parse.urlparse(entry['url']).path.split('/')
        start = path.index('maven2') + 1 if 'maven2' in path else path.index('maven') + 1
        group, artifact, version = '.'.join(path[start:-3]), path[-3], path[-2]
        queries.append({'package': {'name': group + ':' + artifact, 'ecosystem': 'Maven'}, 'version': version})
    request = urllib.request.Request('https://api.osv.dev/v1/querybatch',
                                     data=json.dumps({'queries': queries}).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        results = json.load(response)['results']
    if len(results) != len(queries) or any('error' in result or result.get('next_page_token') for result in results):
        raise ValueError('incomplete advisory query; do not interpret as a clean scan')
    profiles[profile] = [{'package': query['package']['name'], 'version': query['version'],
                          'advisories': [v['id'] for v in result.get('vulns', [])]}
                         for query, result in zip(queries, results)]
print(json.dumps({'queried_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'service': 'https://api.osv.dev/v1/querybatch', 'lock_sha256': BUILD.digest(HERE / 'inputs.lock.json'),
                  'source_scope': args.scope,
                  'scope': f'{len(queries)} direct public Maven inputs per profile; excludes native GIS, JDK and full runtime closure',
                  'profiles': profiles}, indent=2))
