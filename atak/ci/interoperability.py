#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Actual hosted Android scenario; fail closed within an eight-minute outer budget."""
import argparse
import contextlib
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('android_ui', ROOT / 'atak/scenarios/android-ui.py')
ui_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_module)
run = ui_module.scenario.run_bounded


@contextlib.contextmanager
def phase(receipt, name, seconds):
    def expired(signum, frame):
        raise TimeoutError('scenario phase deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    receipt['active_phase'] = name
    try:
        yield
        receipt['passed_phases'].append(name)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def wait_file(path, process, seconds=10):
    deadline = time.monotonic()+seconds
    while not path.exists():
        if process.poll() is not None:
            raise RuntimeError('observer exited before readiness')
        if time.monotonic() >= deadline:
            raise TimeoutError('observer readiness deadline')
        time.sleep(.1)


def stop_observer(process):
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mission-package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=28443)
    parser.add_argument('--ca', required=True)
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--server-leaf-sha256', required=True)
    args = parser.parse_args()
    inputs = ui_module.scenario.inspect_package(args.mission_package)
    if len(inputs['markers']) != 1 or inputs['markers'][0]['lat'] != 0 or inputs['markers'][0]['lon'] != 0:
        parser.error('hosted scenario requires canonical single point at 0,0')
    args.output.mkdir(parents=True, exist_ok=False)
    control = args.output / 'control'
    control.mkdir()
    pod = os.environ.get('ATAK_ADB_POD', '')
    owner = os.environ.get('ATAK_ADB_OWNER', '')
    if not re.fullmatch('[0-9a-f]{16}', owner) or pod != 'atak-scenario-' + owner:
        parser.error('hosted scenario requires a uniquely owned helper identity')
    ui = ui_module.AndroidUI(args.output / 'ui', pod=pod)
    receipt = {'status': 'failed', 'package_sha256': inputs['package_sha256'], 'passed_phases': []}
    challenge = secrets.token_hex(4)
    marker = inputs['markers'][0]
    challenged_name = marker['callsign'] + ' ' + challenge
    receipt['challenge'] = challenge
    process = None
    interrupted_run = False
    def interrupted(signum, frame):
        nonlocal interrupted_run
        interrupted_run = True
        raise TimeoutError("outer scenario deadline or interruption")
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    previous_int = signal.signal(signal.SIGINT, interrupted)
    peer_args = ['--host', args.host, '--connect-host', '127.0.0.1', '--port', str(args.port), '--ca', args.ca, '--cert', args.cert, '--key', args.key, '--server-leaf-sha256', args.server_leaf_sha256, '--mission-package', str(args.mission_package), '--challenge', challenge]
    try:
        with phase(receipt, 'stage-and-ui-import', 150):
            run(['demo/atak-adb.sh', 'start'], timeout=40)
            revision = run(['git', 'rev-parse', 'HEAD:upstream/atak-civ'], timeout=5).decode().strip()
            if revision != '9f6893dd657feacc35ec5de03dad721c2e44170e':
                raise ValueError('official Android source pin changed; review UI selectors')
            receipt['official_atak_source'] = revision
            receipt['installed_apk_sha256'] = ui.apk_identity()
            run(['demo/atak-adb.sh', 'scenario', str(args.mission_package), str(args.output / 'staged')], timeout=45)
            ui.import_package()
            ui.details(marker['callsign'])
            ui.verify_point(marker['callsign'], 0, 0, 'imported')
        with phase(receipt, 'android-broadcast-and-fresh-peer-observation', 120):
            process = subprocess.Popen([sys.executable, str(ROOT / 'atak/scenarios/observe-peer.py'), *peer_args, '--seconds', '115', '--control', str(control), '--output', str(args.output / 'observer')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            wait_file(control / 'ready.json', process)
            edited_at = ui.rename(challenged_name)
            ui.capture('android-challenge')
            ui.share_dialog()
            (control / 'prepare.json').write_text('{}')
            wait_file(control / 'armed.json', process)
            # Strict separation from rename's timestamp, on Android's own clock.
            clock_deadline = time.monotonic()+5
            while True:
                cutoff = int(ui.adb('shell', 'date', '+%s').strip())
                if cutoff >= edited_at+2:
                    break
                if time.monotonic() >= clock_deadline:
                    raise TimeoutError('Android clock did not advance')
                time.sleep(.2)
            # Atomic fence publication: observer never sees a partial JSON file.
            temporary = control / 'share.tmp'
            temporary.write_text(json.dumps({'android_not_before': cutoff}))
            temporary.rename(control / 'share.json')
            ui.broadcast()
            ui.capture('android-broadcast')
            if process.wait(timeout=50) != 0:
                raise RuntimeError('fresh Android challenge was not observed')
            observed = json.loads((args.output / 'observer/receipt.json').read_text())
            if (observed['status'] != 'peer-observed-matching-cot' or observed.get('android_not_before') != cutoff
                    or observed.get('package_sha256') != inputs['package_sha256']
                    or observed.get('received_matching_uids') != [marker['uid']]
                    or observed.get('sends_cot') is not False):
                raise ValueError('observer did not qualify the Share fence')
        with phase(receipt, 'explicit-peer-return-and-android-ui-verification', 100):
            run([sys.executable, str(ROOT / 'atak/ci/reverse-marker.py'), *peer_args, '--output', str(args.output / 'reverse')], timeout=25)
            returned = challenged_name + ' RETURN'
            # Close the contacts/details panes using Android Back, then reopen
            # the actual hierarchy row. No injected SHOW_DETAILS broadcasts.
            ui.adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
            ui.details(returned)
            ui.verify_point(returned, .001, .002, 'returned')
        receipt['status'] = 'ui-import-broadcast-action-fresh-challenge-and-return-verified'
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        stop_observer(process)
        if not interrupted_run:
            try:
                with phase({'passed_phases': []}, 'failure-evidence', 8):
                    ui.capture('first-failure')
            except Exception:
                pass
        raise SystemExit('Android scenario failed: ' + type(error).__name__) from None
    finally:
        stop_observer(process)
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
