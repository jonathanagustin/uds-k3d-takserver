# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit offline protocol/state fixtures; no device, server or TLS network use."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


peer = load('peer', 'atak/scenarios/observe-peer.py')
ui = load('ui', 'atak/scenarios/android-ui.py')
hosted = load('hosted', 'atak/ci/interoperability.py')
reverse = load('reverse', 'atak/ci/reverse-marker.py')


class TLSIdentity(unittest.TestCase):
    def test_pin_and_ca_required_before_any_application_stream(self):
        for pin, mode, allowed in ((None, ssl.CERT_REQUIRED, True), (hashlib.sha256(b'leaf').hexdigest(), ssl.CERT_REQUIRED, True), ('0'*64, ssl.CERT_REQUIRED, False), ('0'*64, ssl.CERT_NONE, False)):
            with self.subTest(pin=pin, mode=mode):
                context = MagicMock(verify_mode=mode, check_hostname=True)
                stream = context.wrap_socket.return_value.__enter__.return_value
                stream.getpeercert.return_value = b'leaf'
                args = types.SimpleNamespace(ca='private-ca', cert='private-cert', key='private-key', host='takserver-stream.uds.dev', connect_host='127.0.0.1', port=28443, server_leaf_sha256=pin)
                with patch.object(peer.ssl, 'create_default_context', return_value=context), patch.object(peer.socket, 'create_connection') as connect:
                    if allowed:
                        with peer.open_peer(args, time.monotonic()+1) as actual:
                            self.assertIs(actual, stream)
                    else:
                        with self.assertRaises(ValueError):
                            with peer.open_peer(args, time.monotonic()+1): self.fail('unverified stream escaped')
                stream.recv.assert_not_called()
                stream.sendall.assert_not_called()
                if mode == ssl.CERT_NONE: connect.assert_not_called()
                self.assertEqual(context.check_hostname, pin is None)

    def test_ca_or_hostname_failure_never_falls_back(self):
        context = MagicMock(verify_mode=ssl.CERT_REQUIRED, check_hostname=True)
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError('PRIVATE certificate failure')
        args = types.SimpleNamespace(ca='ca', cert='cert', key='key', host='host', port=8089)
        with patch.object(peer.ssl, 'create_default_context', return_value=context), patch.object(peer.socket, 'create_connection'):
            with self.assertRaises(ssl.SSLCertVerificationError):
                with peer.open_peer(args, time.monotonic()+1): self.fail('fallback')
        context.wrap_socket.assert_called_once()
        self.assertTrue(context.check_hostname)


class FreshShareFence(unittest.TestCase):
    marker = {'uid': 'synthetic-test', 'type': 'a-f-G-U-C', 'lat': 0., 'lon': 0., 'callsign': 'TEST aabbccdd'}

    def event(self, timestamp):
        return f'<event uid="synthetic-test" type="a-f-G-U-C" time="{timestamp}"><point lat="0" lon="0"/><detail><contact callsign="TEST aabbccdd"/></detail></event>'.encode()

    def test_retained_challenge_is_not_fresh_share(self):
        stream = MagicMock()
        stream.recv.side_effect = [self.event('2026-01-01T00:00:00Z'), b'']
        cutoff = 1767225602
        with self.assertRaises(RuntimeError): peer.observe(stream, [self.marker], time.monotonic()+1, cutoff)
        stream.recv.side_effect = [self.event('2026-01-01T00:00:00Z'), self.event('2026-01-01T00:00:02Z')]
        receipt = peer.observe(stream, [self.marker], time.monotonic()+1, cutoff)
        self.assertEqual(receipt['android_not_before'], cutoff)
        self.assertEqual(receipt['fresh_event_time'], '2026-01-01T00:00:02Z')
        stream.sendall.assert_not_called()

    def test_ready_drain_arm_then_share_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory)
            clock = [0.]
            def now():
                clock[0] += .2
                return clock[0]
            stream = MagicMock()
            def receive(size):
                self.assertTrue((control/'ready.json').exists())
                if not (control/'prepare.json').exists():
                    (control/'prepare.json').write_text('{}')
                    return b'retained-before-share'
                if (control/'armed.json').exists():
                    (control/'share.json').write_text('{"android_not_before": 123}')
                raise socket.timeout()
            stream.recv.side_effect = receive
            with patch.object(peer.time, 'monotonic', side_effect=now):
                cutoff, discarded = peer.share_fence(stream, control, 10)
            self.assertEqual(cutoff, 123)
            self.assertGreater(discarded, 0)
            stream.sendall.assert_not_called()

    def test_absent_share_or_receive_overflow_never_ready_for_success(self):
        for overflow in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                stream = MagicMock()
                stream.recv.side_effect = [b'x'*(peer.LIMIT+1)] if overflow else [b'']
                with self.assertRaises((ValueError, RuntimeError)):
                    peer.share_fence(stream, Path(directory), time.monotonic()+1)


class ActualUIStates(unittest.TestCase):
    def node(self, text='TEST', rid='cotInfoNameEdit', enabled='true'):
        return ET.fromstring(f'<hierarchy><node text="{text}" resource-id="com.atakmap.app.civ:id/{rid}" enabled="{enabled}" bounds="[0,0][100,100]"/></hierarchy>')

    def test_unique_enabled_nodes_only(self):
        tree = self.node()
        self.assertEqual(ui.select(tree, rid='cotInfoNameEdit').get('text'), 'TEST')
        tree.append(tree[0])
        with self.assertRaises(LookupError): ui.select(tree, rid='cotInfoNameEdit')
        with self.assertRaises(LookupError): ui.select(self.node(enabled='false'), text='TEST')

    def test_import_uses_actual_file_browser_and_broadcast_target(self):
        device = ui.AndroidUI('/unused')
        with patch.object(device, 'confirm_file_selected') as selection, patch.object(device, 'tool') as tool, patch.object(device, 'tap') as tap, patch.object(device, 'find', return_value=ET.Element('node', text='/sdcard')):
            device.import_package()
            device.share_dialog()
            device.broadcast()
        tool.assert_called_once_with('Import')
        selection.assert_called_once_with('atak-synthetic-scenario.dpk')
        self.assertIn(unittest.mock.call(text='Local SD'), tap.call_args_list)
        self.assertIn(unittest.mock.call(rid='importManagerBrowserFileName', text='atak-synthetic-scenario.dpk'), tap.call_args_list)
        self.assertEqual(tap.call_args_list[-1], unittest.mock.call(rid='contact_list_button_send_to_all', text='Broadcast'))
        self.assertFalse(any('peer' in str(call) for call in tap.call_args_list))

    def test_installed_apk_must_match_existing_driver_artifact(self):
        device = ui.AndroidUI('/unused')
        for actual in ('a'*64, 'b'*64):
            with self.subTest(actual=actual), patch.object(device, 'adb', side_effect=[b'package:/data/app/base.apk', (actual+' /data/app/base.apk').encode()]), patch.object(ui.scenario, 'run_bounded', return_value=('a'*64+' /atak-civ.apk').encode()):
                if actual == 'a'*64:
                    self.assertEqual(device.apk_identity(), actual)
                else:
                    with self.assertRaises(ValueError): device.apk_identity()

    def test_wrong_file_selection_and_missing_tool_fail_closed(self):
        device = ui.AndroidUI('/unused')
        tree = ET.fromstring('<hierarchy><node><node text="atak-synthetic-scenario.dpk" resource-id="app:id/importManagerBrowserFileName" enabled="true" bounds="[0,0][100,100]"/><node resource-id="app:id/importManagerBrowserFileSelected" checked="false"/></node></hierarchy>')
        with patch.object(device, 'tree', return_value=tree):
            with self.assertRaises(ValueError): device.confirm_file_selected('atak-synthetic-scenario.dpk')
        with patch.object(device, 'tree', return_value=ET.Element('hierarchy')), patch.object(device, 'tap'), patch.object(device, 'find', return_value=ET.Element('node', bounds='[0,0][100,100]')), patch.object(device, 'adb') as adb:
            with self.assertRaises(LookupError): device.tool('Import')
        self.assertEqual(adb.call_count, 6)
        self.assertTrue(all('swipe' in call.args for call in adb.call_args_list))

    def test_return_search_replaces_retained_query_and_only_hides_active_ime(self):
        device = ui.AndroidUI('/unused')
        search = ET.Element('node', text='OLD')
        actual = ET.Element('node', text='TEST RETURN')
        with patch.object(device, 'tool'), patch.object(device, 'tree', return_value=self.node(rid='hierarchy_search')), patch.object(device, 'find', side_effect=[search, actual]), patch.object(device, 'tap') as tap, patch.object(device, 'adb', return_value=b'mInputShown=true') as adb:
            device.details('TEST RETURN')
        self.assertIn(unittest.mock.call('shell', 'input', 'keyevent', 'KEYCODE_DEL', 'KEYCODE_DEL', 'KEYCODE_DEL'), adb.call_args_list)
        self.assertIn(unittest.mock.call('shell', 'input', 'keyevent', 'KEYCODE_BACK'), adb.call_args_list)
        self.assertNotIn(unittest.mock.call(rid='hierarchy_search_btn'), tap.call_args_list)
        with patch.object(device, 'adb', return_value=b'mInputShown=false') as adb:
            device.hide_keyboard()
        self.assertEqual(adb.call_count, 1)

    def test_empty_screenshot_is_not_map_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            device = ui.AndroidUI(directory)
            with patch.object(device, 'adb', side_effect=[b'', b'<hierarchy/>', b'']):
                with self.assertRaises(ValueError): device.capture('map')
            self.assertFalse((Path(directory)/'map.png').exists())

    def test_wrong_android_coordinates_fail_before_map_evidence(self):
        device = ui.AndroidUI('/unused')
        values = [ET.Element('node', text='TEST'), ET.Element('node', text='1'), ET.Element('node', text='0')]
        with patch.object(device, 'find', side_effect=values), patch.object(device, 'tap'), patch.object(device, 'capture') as capture:
            with self.assertRaises(ValueError): device.verify_point('TEST', 0., 0., 'imported')
        capture.assert_not_called()


class OrchestrationAndCleanup(unittest.TestCase):
    def test_failed_setup_removes_private_work_and_test_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uds = root/'uds'
            uds.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\ncase "$*" in *" wait "*) exit 1;; esac\n')
            uds.chmod(0o755)
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], RUNNER_TEMP=str(root), CALL_LOG=str(root/'calls'))
            result = subprocess.run(['bash', 'atak/ci/interoperability.sh', str(root/'out')], cwd=ROOT, env=env, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(list(root.glob('atak-scenario.*')))
            self.assertIn('delete takclient atak-peer-', (root/'calls').read_text())
            self.assertIn('delete pod -n atak atak-demo-adb', (root/'calls').read_text())

    def test_cleanup_failure_cannot_leave_success_or_mask_first_failure(self):
        for original in ('failed', 'ui-import-broadcast-action-fresh-challenge-and-return-verified'):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root/'out'
                output.mkdir()
                (output/'receipt.json').write_text(json.dumps({'status':original, 'error_type':'FirstFailure'}))
                uds = root/'uds'
                uds.write_text('#!/bin/sh\ncase "$*" in *" wait "*|*" delete takclient "*) exit 1;; esac\n')
                uds.chmod(0o755)
                env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], RUNNER_TEMP=str(root))
                result = subprocess.run(['bash', 'atak/ci/interoperability.sh', str(output)], cwd=ROOT, env=env, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(json.loads((output/'cleanup.json').read_text())['cleanup_verified'])
                receipt = json.loads((output/'receipt.json').read_text())
                self.assertEqual(receipt['status'], 'failed' if original == 'failed' else 'failed-cleanup')
                self.assertEqual(receipt['error_type'], 'FirstFailure')
                self.assertFalse(list(root.glob('atak-scenario.*')))

    def test_observer_cleanup_kills_owned_process_group(self):
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        with patch.object(hosted.os, 'killpg') as kill:
            hosted.stop_observer(process)
        kill.assert_called_once_with(1234, hosted.signal.SIGKILL)
        process.wait.assert_called_once_with(timeout=5)

    def test_reverse_is_an_explicit_changed_update_not_fixture_replay(self):
        marker = FreshShareFence.marker.copy()
        payload = reverse.update(marker, 'aabbccdd')
        event = ET.fromstring(payload)
        self.assertEqual(event.get('uid'), marker['uid'])
        self.assertEqual(event.find('point').get('lat'), '0.001')
        self.assertEqual(event.find('point').get('lon'), '0.002')
        self.assertTrue(event.find('detail/contact').get('callsign').endswith(' RETURN'))
        self.assertEqual(event.find('remarks'), None)
        with self.assertRaises(ValueError): reverse.update(marker, 'not-synthetic')

    def test_phase_exception_cannot_mark_phase_passed(self):
        receipt = {'passed_phases': []}
        with self.assertRaises(RuntimeError):
            with hosted.phase(receipt, 'failed-ui', 1): raise RuntimeError('fixture failure')
        self.assertEqual(receipt['passed_phases'], [])

    def test_controller_requires_every_actual_phase_and_cleans_owned_observer(self):
        builder = load('fixture_builder', 'takx/mission-package/build_fixture.py')
        for failure in ('import', 'observer', 'observer-identity', 'return-ui', None):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = root/'fixture.dpk'
                builder.build(package)
                output = root/'out'
                actions = []
                class Device:
                    def __init__(self, path): pass
                    def apk_identity(self): return 'a'*64
                    def import_package(self):
                        actions.append('import')
                        if failure == 'import': raise LookupError('mock import state absent')
                    def details(self, callsign): pass
                    def verify_point(self, callsign, lat, lon, name):
                        if name == 'returned' and failure == 'return-ui': raise ValueError('mock wrong return point')
                    def rename(self, callsign):
                        actions.append('rename')
                        return 100
                    def capture(self, name): pass
                    def share_dialog(self): actions.append('share-dialog')
                    def adb(self, *command): return b'102'
                    def broadcast(self):
                        actions.append('broadcast')
                        fence = json.loads((output/'control/share.json').read_text())
                        observer = output/'observer'
                        observer.mkdir()
                        (observer/'receipt.json').write_text(json.dumps({'status':'peer-observed-matching-cot', 'android_not_before':fence['android_not_before'], 'package_sha256': '0'*64 if failure == 'observer-identity' else hashlib.sha256(package.read_bytes()).hexdigest(), 'received_matching_uids':['synthetic-android-mission-point'], 'sends_cot':False}))
                process = MagicMock(pid=123)
                process.poll.return_value = None
                process.wait.return_value = 1 if failure == 'observer' else 0
                def ready(path, process): actions.append(path.stem)
                argv = ['scenario', '--mission-package', str(package), '--output', str(output), '--host', 'example.invalid', '--ca', 'PRIVATE-ca', '--cert', 'PRIVATE-cert', '--key', 'PRIVATE-key', '--server-leaf-sha256', '0'*64]
                with patch('sys.argv', argv), patch.object(hosted.ui_module, 'AndroidUI', Device), patch.object(hosted, 'run', side_effect=lambda command, **kwargs: b'9f6893dd657feacc35ec5de03dad721c2e44170e\n' if command[0] == 'git' else b'') as commands, patch.object(hosted.subprocess, 'Popen', return_value=process), patch.object(hosted, 'wait_file', side_effect=ready), patch.object(hosted, 'stop_observer') as stop, patch.object(hosted.secrets, 'token_hex', return_value='aabbccdd'):
                    if failure:
                        with self.assertRaises(SystemExit): hosted.main()
                    else:
                        hosted.main()
                receipt = json.loads((output/'receipt.json').read_text())
                self.assertNotIn('PRIVATE', json.dumps(receipt))
                if failure:
                    self.assertEqual(receipt['status'], 'failed')
                    self.assertLess(len(receipt['passed_phases']), 3)
                else:
                    self.assertEqual(len(receipt['passed_phases']), 3)
                    self.assertEqual(actions, ['import', 'ready', 'rename', 'share-dialog', 'armed', 'broadcast'])
                reverse_calls = [call for call in commands.call_args_list if any(str(arg).endswith('reverse-marker.py') for arg in call.args[0])]
                self.assertEqual(bool(reverse_calls), failure in (None, 'return-ui'))
                expected_process = None if failure == 'import' else process
                self.assertEqual(stop.call_count, 2 if failure else 1)
                stop.assert_called_with(expected_process)
