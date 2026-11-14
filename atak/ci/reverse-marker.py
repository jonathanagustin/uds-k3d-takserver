#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Send one explicit synthetic reverse update, separate from the read-only observer."""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import re
import signal
import time
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('observer', Path(__file__).resolve().parents[1] / 'scenarios/observe-peer.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def update(marker, challenge):
    if not re.fullmatch('[0-9a-f]{8}', challenge):
        raise ValueError('invalid synthetic challenge')
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = lambda value: value.isoformat().replace('+00:00', 'Z')
    event = ET.Element('event', version='2.0', uid=marker['uid'], type=marker['type'], how='m-g', time=stamp(now), start=stamp(now), stale=stamp(now+datetime.timedelta(minutes=5)))
    ET.SubElement(event, 'point', lat='0.001', lon='0.002', hae='0', ce='9999999', le='9999999')
    detail = ET.SubElement(event, 'detail')
    ET.SubElement(detail, 'contact', callsign=marker['callsign'] + ' ' + challenge + ' RETURN')
    ET.SubElement(detail, 'remarks').text = 'SYNTHETIC TEST reverse update from the explicit test peer'
    return ET.tostring(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('host', 'connect-host', 'ca', 'cert', 'key', 'server-leaf-sha256', 'challenge'):
        parser.add_argument('--' + option, required=option not in ('connect-host', 'server-leaf-sha256'))
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--mission-package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inputs = observer.scenario.inspect_package(args.mission_package)
    if len(inputs['markers']) != 1:
        parser.error('reverse test requires exactly one fixture marker')
    payload = update(inputs['markers'][0], args.challenge)
    args.output.mkdir(exist_ok=False)
    receipt = {'status': 'failed', 'package_sha256': inputs['package_sha256'], 'sends_cot': True}
    def expired(signum, frame):
        raise TimeoutError('reverse deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(20)
    try:
        with observer.open_peer(args, time.monotonic()+20) as stream:
            stream.settimeout(5)
            stream.sendall(payload)
        receipt['status'] = 'reverse-update-sent-unverified'
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        raise SystemExit('reverse update failed: ' + type(error).__name__) from None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
