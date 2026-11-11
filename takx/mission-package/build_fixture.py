#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Pack reviewed synthetic bytes; this is not a mission-package importer/validator."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = {'MANIFEST/manifest.xml':'manifest.xml',
         'cot/synthetic-android-mission-point.cot':'point.cot', 'files/README.txt':'README.txt'}


def build(output):
    lock = json.loads((ROOT/'fixtures.lock.json').read_text())
    inputs = {}
    for target, source in FILES.items():
        data = (ROOT/'fixtures'/source).read_bytes()
        if hashlib.sha256(data).hexdigest() != lock['files'][source]['sha256']:
            raise ValueError('synthetic fixture hash mismatch')
        inputs[target] = data
    # Fixed ZIP metadata, stored entries and exclusive output make retries explicit.
    with Path(output).open('xb') as stream, zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
        for target,data in sorted(inputs.items()):
            entry = zipfile.ZipInfo(target,(1980,1,1,0,0,0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry,data)
    return hashlib.sha256(Path(output).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        digest=build(args.output)
        print('Synthetic mission package SHA256 '+digest)
    except (ValueError,OSError):
        parser.exit(1,'Synthetic fixture build refused; use a fresh output path\n')


if __name__=='__main__':main()
