# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise complete failed command captures without a container or compiler."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
import capture_failure
import draco as local
import producer


class FailureLogsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'producer'
        self.root.mkdir()
        self.output=Path(self.temp.name)/'sanitized'

    def failed_command(self, name='container', code=None):
        if code is None:
            code='import sys;print("password=PRIVATE_NATIVE_PASSWORD");sys.exit(7)'
        with self.assertRaises(ValueError):
            producer.run([sys.executable,'-c',code],self.root,name,2)

    def test_nonzero_completed_command_is_redacted_with_status_and_no_arguments(self):
        self.failed_command()
        status=local.load(self.root/'container.status.json')
        self.assertTrue(status['complete'])
        self.assertEqual(status['returncode'],7)
        capture_failure.capture(self.root,self.output)
        text=(self.output/'host-container.log').read_text()
        self.assertNotIn('PRIVATE_NATIVE_PASSWORD',text)
        self.assertIn('[REDACTED]',text)
        index=local.load(self.output/'index.json')
        self.assertFalse(index['qualification'])
        self.assertNotIn('command',json.dumps(index))
        self.assertEqual(index['logs'][0]['returncode'],7)

    def test_timed_out_prefix_is_never_exported(self):
        with self.assertRaises(ValueError):
            producer.run([sys.executable,'-u','-c','import time;print("PRIVATE_PREFIX");time.sleep(5)'],
                         self.root,'timeout',.1)
        self.assertFalse(local.load(self.root/'timeout.status.json')['complete'])
        capture_failure.capture(self.root,self.output)
        self.assertEqual(list(self.output.iterdir()),[self.output/'index.json'])

    def test_tampered_log_cannot_be_credited_as_complete(self):
        self.failed_command()
        (self.root/'container.log').write_text('PRIVATE_TAMPERED')
        capture_failure.capture(self.root,self.output)
        self.assertFalse(local.load(self.output/'index.json')['logs'][0]['exported'])
        self.assertFalse((self.output/'host-container.log').exists())

    def test_invalid_utf8_complete_capture_is_omitted(self):
        self.failed_command(code='import os;os.write(1,b"\\xffPRIVATE_BYTES");raise SystemExit(2)')
        capture_failure.capture(self.root,self.output)
        self.assertFalse(local.load(self.output/'index.json')['logs'][0]['exported'])
        self.assertFalse((self.output/'host-container.log').exists())

    def test_unrecorded_log_and_recursive_source_log_are_never_selected(self):
        (self.root/'unrecorded.log').write_text('PRIVATE_UNRECORDED')
        source=self.root/'build/work';source.mkdir(parents=True)
        (source/'source.log').write_text('PRIVATE_SOURCE')
        capture_failure.capture(self.root,self.output)
        self.assertEqual(local.load(self.output/'index.json')['logs'],[])

    def test_oversized_capture_is_omitted_without_reading_it(self):
        log=self.root/'large.log'
        with log.open('wb') as stream:stream.truncate(capture_failure.MAX_LOG+1)
        (self.root/'large.status.json').write_bytes(local.canonical({
            'schema':'uds-native-command-log-v1','complete':True,'returncode':1,
            'bytes':capture_failure.MAX_LOG+1,'sha256':'0'*64}))
        capture_failure.capture(self.root,self.output)
        self.assertFalse(local.load(self.output/'index.json')['logs'][0]['exported'])

    def test_aggregate_budget_cannot_export_a_complete_log(self):
        self.failed_command()
        with patch.object(capture_failure,'MAX_TOTAL',1):
            capture_failure.capture(self.root,self.output)
        self.assertFalse(local.load(self.output/'index.json')['logs'][0]['exported'])

    def test_symlink_log_is_rejected(self):
        self.failed_command()
        log=self.root/'container.log';log.unlink();log.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):capture_failure.capture(self.root,self.output)

    def test_inner_build_scope_is_exported_with_distinct_safe_name(self):
        build=self.root/'build';build.mkdir()
        producer.run([sys.executable,'-c','print("actual fixture diagnostic")'],build,'configure')
        capture_failure.capture(self.root,self.output)
        self.assertIn('actual fixture diagnostic',(self.output/'build-configure.log').read_text())

    def test_workflow_never_uploads_raw_logs_or_failed_sanitization(self):
        workflow=yaml.safe_load((local.ROOT/'.github/workflows/native-cache.yaml').read_text())
        steps=workflow['jobs']['build']['steps']
        sanitize=next(s for s in steps if s.get('id')=='failure-logs')
        upload=next(s for s in steps if s['name']=='Retain sanitized native build failure logs')
        self.assertIn('failure()',sanitize['if'])
        self.assertIn('!cancelled()',sanitize['if'])
        self.assertIn("steps.failure-logs.outcome == 'success'",upload['if'])
        self.assertEqual(upload['with']['path'],'${{ runner.temp }}/native-failure-sanitized')
        self.assertNotIn('draco-producer',upload['with']['path'])


if __name__=='__main__':unittest.main()
