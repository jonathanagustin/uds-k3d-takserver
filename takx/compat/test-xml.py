#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in real parser/unchanged pinned XMLUtils tests; no fetch or engine stubs."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
JAR_SHA256 = 'f264dd9f79a1fde10ce5ecc53221eff24be4c9331c830b7d52f2f08a7b633de2'
CONSUMER = 'takkernel/engine/src/main/java/com/atakmap/coremap/xml/XMLUtils.java'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--kxml-jar', type=Path, required=True)
    args = parser.parse_args()
    jar = args.kxml_jar.resolve()
    if hashlib.sha256(jar.read_bytes()).hexdigest() != JAR_SHA256:
        parser.error('kXML2 JAR checksum differs from the verified 2.3.0 dependency')
    observed = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    if observed != REVISION:
        parser.error('ATAK source revision differs from pinned official source')
    data = subprocess.check_output(['git', '-C', str(args.source), 'show', f'{REVISION}:{CONSUMER}'])
    with tempfile.TemporaryDirectory(prefix='takx-xml-') as temporary:
        stage = Path(temporary)
        consumer = stage / 'XMLUtils.java'
        consumer.write_bytes(data)
        subprocess.run(['javac', '--release', '11', '-Xlint:all', '-cp', str(jar), '-d', temporary,
                        str(HERE / 'src/main/java/android/util/Xml.java'), str(consumer),
                        str(HERE / 'src/test/java/XmlCompatibilityTest.java')], check=True)
        subprocess.run(['java', '-ea', '-cp', temporary + ':' + str(jar),
                        'XmlCompatibilityTest'], check=True, timeout=30)


if __name__ == '__main__':
    main()
