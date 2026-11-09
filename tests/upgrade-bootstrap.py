#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Select a source-validated checkpoint without executing released code."""
import argparse
import json
from pathlib import Path
import sys


BOOTSTRAPS = {
    ('1.15.2-upstream', '2.0.3'): '1.15.0',  # v0.6 needs this older controller preload.
    ('1.16.0-upstream', '2.0.7'): '1.16.0',  # Known recent releases use the matching Core.
}


def select_bootstrap(core_refs, package):
    if not isinstance(core_refs, list) or len(core_refs) != 1 or not isinstance(core_refs[0], str) or not core_refs[0]:
        raise ValueError('Released bundle must contain exactly one core-base reference')
    dependencies = package.get('dependencies') if isinstance(package, dict) else None
    pepr = dependencies.get('pepr') if isinstance(dependencies, dict) else None
    if not isinstance(pepr, str) or not pepr:
        raise ValueError('Released Pepr manifest must pin dependencies.pepr')
    metadata = package.get('pepr')
    controller = metadata.get('peprVersion') if isinstance(metadata, dict) else None
    if not isinstance(controller, str) or not controller or controller != pepr:
        raise ValueError('Released Pepr build and controller versions must both be pinned and equal')
    pair = (core_refs[0], pepr)
    if pair not in BOOTSTRAPS:
        raise ValueError('Unvalidated released Core/Pepr bootstrap combination; review checkpoint compatibility')
    return BOOTSTRAPS[pair]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate bootstrap metadata key')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core_refs', type=Path)
    parser.add_argument('pepr_package', type=Path)
    args = parser.parse_args()
    with args.core_refs.open() as stream:
        refs = json.load(stream, object_pairs_hook=unique_object)
    with args.pepr_package.open() as stream:
        package = json.load(stream, object_pairs_hook=unique_object)
    print(select_bootstrap(refs, package))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(f'Cannot select released bootstrap: {error}')
