#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Locate immutable published packages across the repository rename."""
import re
import sys


def published_package_ref(version):
    match = re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version)
    if not match:
        raise ValueError('Expected a stable semantic version, optionally prefixed with v')
    parsed = tuple(map(int, match.groups()))
    namespace = "uds-k3d-takserver" if parsed < (0, 11, 0) else "uds-takserver"
    normalized = '.'.join(match.groups())
    return f'oci://ghcr.io/jonathanagustin/{namespace}/takserver:{normalized}-upstream'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: published_package_ref.py VERSION')
    try:
        print(published_package_ref(sys.argv[1]))
    except ValueError as error:
        sys.exit(str(error))
