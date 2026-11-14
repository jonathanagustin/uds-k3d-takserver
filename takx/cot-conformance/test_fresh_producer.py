# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline proof guards; no native library, compiler or network is used."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('cot_check_for_fresh_tests', HERE/'check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
F = CHECK.fresh_producer


class FreshProducerGuards(unittest.TestCase):
    def test_explicit_complete_binding_roots_and_unsafe_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {}
            for key in F.KEYS:
                path = root/key; path.mkdir(); values[key] = str(path)
            config = root/'inputs.json'; config.write_text(json.dumps(values))
            self.assertEqual(set(F.bindings(config)), F.KEYS)
            for mutation in ('missing', 'extra', 'relative', 'alias'):
                with self.subTest(mutation=mutation):
                    data = dict(values)
                    if mutation == 'missing': data.pop('source')
                    elif mutation == 'extra': data['unknown'] = str(root)
                    elif mutation == 'relative': data['source'] = 'relative'
                    else: data['source'] = str(root/'source/../source')
                    config.write_text(json.dumps(data))
                    with self.assertRaises(ValueError): F.bindings(config)
            for raw in ('{"source":1,"source":2}', '{"value":NaN}', '{"value":Infinity}'):
                config.write_text(raw)
                with self.assertRaises(ValueError): F.load(config)
            config.write_bytes(b'x'*17)
            with self.assertRaisesRegex(ValueError, 'bounded'): F.load(config, 16)
            config.unlink(); config.symlink_to(root/'source')
            with self.assertRaisesRegex(ValueError, 'symlink'): F.load(config)

    def test_incomplete_relabelled_or_overclaimed_producer_refused(self):
        valid = dict(profile='public-commoncommo-native-jni', version='1.17.2', source_revision=CHECK.PIN,
            fresh_dependency_build=True, fresh_core_build=True, fresh_jni_build=True,
            actual_commoncommo_jni=True, throwing_logger_exceptions_isolated=True, quic_compiled=True,
            all_callback_exception_paths=False, quic_peer_handshake=False, takserver_interoperability=False,
            full_sdk=False, takx_client=False)
        F.scope(valid)
        for key in valid:
            with self.subTest(field=key):
                changed = dict(valid)
                changed[key] = not valid[key] if type(valid[key]) is bool else 'unreviewed'
                with self.assertRaises(ValueError): F.scope(changed)
                if type(valid[key]) is bool:
                    changed[key] = int(valid[key])
                    with self.assertRaises(ValueError): F.scope(changed)

    def test_wrong_reviewed_receipt_stops_before_loading_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prefix = root/'install'; prefix.mkdir()
            jdk = root/'jdk'; jdk.mkdir(); receipt = root/'complete.json'; receipt.write_text('{}')
            with patch.object(F, 'builder', side_effect=AssertionError('must not load')):
                with self.assertRaisesRegex(ValueError, 'reviewed receipt differs'):
                    F.verify(root/'missing-inputs.json', prefix, receipt, jdk, '0'*64, root/'output')

    def test_output_inside_input_is_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prefix = root/'install'; prefix.mkdir()
            jdk = root/'jdk'; jdk.mkdir(); receipt = root/'complete.json'; receipt.write_text('{}')
            for parent in (prefix, jdk, receipt.parent):
                out = parent/'new-output'
                args = SimpleNamespace(output=out, prefix=prefix, jdk=jdk, receipt=receipt,
                                       fresh_bindings=None, producer_receipt_sha256=None)
                with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, 'overlaps'):
                    CHECK.run(args)
                self.assertFalse(out.exists())

    def test_fresh_flags_are_explicit_and_default_stays_offline(self):
        result = subprocess.run([sys.executable, '-B', str(HERE/'check.py')], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        for flags in (['--fresh-bindings', '/not-read'], ['--producer-receipt-sha256', '0'*64]):
            result = subprocess.run([sys.executable, '-B', str(HERE/'check.py'), *flags], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b'require each other and --run', result.stderr)

    def test_total_deadline_covers_preflight_and_restores_handler(self):
        code = '''import importlib.util, os, signal, sys
s=importlib.util.spec_from_file_location('check', sys.argv[1])
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
old=signal.getsignal(signal.SIGALRM)
m.run=lambda args: os.kill(os.getpid(), signal.SIGALRM)
try: m.bounded_run(None)
except TimeoutError: pass
else: raise AssertionError('total deadline was not enforced')
assert signal.getsignal(signal.SIGALRM)==old
assert signal.alarm(0)==0
'''
        subprocess.run([sys.executable, '-B', '-c', code, str(HERE/'check.py')], check=True, capture_output=True, timeout=5)

    def test_patched_postimages_are_reconstructed_not_self_attested(self):
        for mutation in ('valid', 'source', 'source-and-manifest', 'extra-manifest', 'owned-patch'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); source=root/'git'; source.mkdir(); producer=root/'producer'; producer.mkdir()
                workspace=root/'workspace'; workspace.mkdir(); recipe=root/'recipe'; recipe.mkdir()
                for name in ('core/a.cpp', 'jni/native/b.cpp'):
                    path=source/'commoncommo'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('before\n')
                def git(*args):
                    return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.DEVNULL, timeout=5)
                git('init', '-q'); git('add', '.')
                git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'fixture')
                revision=git('rev-parse', 'HEAD').decode().strip()
                first=recipe/'first.patch'; first.write_text('--- a/commoncommo/core/a.cpp\n+++ b/commoncommo/core/a.cpp\n@@ -1 +1 @@\n-before\n+after\n')
                jni=recipe/'jni.patch'; jni.write_text('--- a/jni/native/b.cpp\n+++ b/jni/native/b.cpp\n@@ -1 +1 @@\n-before\n+after\n')
                official={}
                for row in git('ls-tree','-r','-z',revision,'--','commoncommo').rstrip(b'\0').split(b'\0'):
                    meta,name=row.split(b'\t'); oid=meta.decode().split()[2]; data=git('cat-file','blob',oid)
                    official[name.decode()]={'git_blob':oid,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                expected={}
                for name in ('core/a.cpp', 'jni/native/b.cpp'):
                    path=producer/'commoncommo'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('after\n')
                    expected[name]={'bytes':path.stat().st_size,'sha256':F.digest(path)}
                jni_hash=F.digest(jni)
                if mutation in ('source', 'source-and-manifest'):
                    path=producer/'commoncommo/core/a.cpp';path.write_text('forged\n')
                    if mutation=='source-and-manifest': expected['core/a.cpp']={'bytes':path.stat().st_size,'sha256':F.digest(path)}
                elif mutation=='extra-manifest':expected['unknown.cpp']={'bytes':1,'sha256':'0'*64}
                elif mutation=='owned-patch':jni.write_text(jni.read_text().replace('+after','+forged'))
                (producer/'commoncommo-sources.json').write_text(json.dumps({'git':official,'patched':expected}))
                def check_record(path, entries):
                    for name, entry in entries.items():
                        F.require(F.digest(path/name)==entry['sha256'], 'actual source differs')
                build=SimpleNamespace(LOCK={'revision':revision,'jni_patch':{'path':'jni.patch','sha256':jni_hash}},
                    HERE=recipe, native=SimpleNamespace(git=lambda _source,*args:git(*args), relative=Path),
                    inputs=SimpleNamespace(verify_patches=lambda *_args:[first]), check_record=check_record)
                if mutation=='valid': F.official_sources(build, producer, source, workspace, Path('/usr/bin/patch').resolve())
                else:
                    with self.assertRaises(ValueError): F.official_sources(build, producer, source, workspace, Path('/usr/bin/patch').resolve())


if __name__ == '__main__':
    unittest.main()
