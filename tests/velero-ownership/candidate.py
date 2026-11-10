#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Write reviewed isolated bundle variants, or bind their built archive hashes."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import yaml

SPEC = importlib.util.spec_from_file_location('ownership_prepare', Path(__file__).with_name('prepare.py'))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
SPEC = importlib.util.spec_from_file_location('ownership_drive', Path(__file__).with_name('drive.py'))
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
ROOT = Path(__file__).resolve().parents[2]


def variants(bundle, exemption):
    core = P.prepare(bundle, exemption)
    core['packages'] = [p for p in core['packages'] if p['name'] in ('core-base', 'core-backup-restore', 'takserver')]
    require = D.require
    require({p['name'] for p in core['packages']} == {'core-base', 'core-backup-restore', 'takserver'}, 'missing trial package')
    result = {'core': core}
    for name in ('detach', 'clean'):
        doc = copy.deepcopy(core)
        doc['packages'] = [p for p in doc['packages'] if p['name'] == 'core-backup-restore']
        values = doc['packages'][0]['overrides']['velero']['velero']['values']
        next(v for v in values if v['path'] == 'deployNodeAgent')['value'] = False
        if name == 'clean':
            values[:] = [v for v in values if v['path'] != 'configMaps.node-agent-config']
        result[name] = doc
    for name, doc in result.items():
        doc['metadata']['name'] = 'takserver-owner-' + name
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--exemption', type=Path, required=True)
    prepare.add_argument('--directory', type=Path, required=True)
    bind = commands.add_parser('bind')
    bind.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.operation == 'prepare':
        D.require(not directory.exists(), 'candidate directory already exists')
        source = ROOT / 'bundle/full/uds-bundle.yaml'
        docs = variants(yaml.safe_load(source.read_text()), yaml.safe_load(args.exemption.read_text()))
        directory.mkdir(parents=True, mode=0o700)
        for name, doc in docs.items():
            dest = directory / name
            dest.mkdir()
            for package in doc['packages']:
                if 'path' in package:
                    package['path'] = os.path.relpath((source.parent / package['path']).resolve(), dest)
                for charts in package.get('overrides', {}).values():
                    for chart in charts.values():
                        if 'valuesFiles' in chart:
                            chart['valuesFiles'] = [os.path.relpath((source.parent / value).resolve(), dest) for value in chart['valuesFiles']]
            (dest / 'uds-bundle.yaml').write_text(yaml.safe_dump(doc, sort_keys=False))
        (directory / 'uds-config.yaml').write_bytes((ROOT / 'bundle/full/uds-config.yaml').read_bytes())
        receipt = {'schema': 1, 'sourceSHA': os.environ.get('GITHUB_SHA'),
                   'files': {str(p.relative_to(directory)): D.digest(p) for p in directory.rglob('*') if p.is_file()},
                   'exemptionSHA256': D.digest(args.exemption)}
        (directory / 'candidate.json').write_text(json.dumps(receipt, indent=2) + '\n')
    else:
        receipt = json.loads((directory / 'candidate.json').read_text())
        D.require(receipt['schema'] == 1 and receipt['sourceSHA'] == os.environ.get('GITHUB_SHA'), 'candidate source changed')
        for relative, digest in receipt['files'].items():
            D.require(D.digest(directory / relative) == digest, 'prepared candidate changed before binding')
        files = {'config': {'path': 'uds-config.yaml', 'sha256': D.digest(directory / 'uds-config.yaml')}}
        for name in ('core', 'detach', 'clean'):
            matches = list((directory / name).glob('uds-bundle-*.tar.zst'))
            D.require(len(matches) == 1, 'exactly one built archive required for ' + name)
            files[name] = {'path': str(matches[0].relative_to(directory)), 'sha256': D.digest(matches[0])}
        with (directory / 'plan.json').open('x') as stream:
            json.dump({'schema': 1, 'sourceSHA': receipt['sourceSHA'], 'files': files}, stream, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    main()
