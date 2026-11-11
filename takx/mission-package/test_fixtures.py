# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Always-offline fixture/provenance guards; actual Java qualification is separate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('builder',ROOT/'build_fixture.py')
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)
SPEC=importlib.util.spec_from_file_location('qualifier',ROOT/'qualify.py')
Q=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(Q)
SPEC=importlib.util.spec_from_file_location('projector',ROOT/'project_sources.py')
P=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(P)


class FixtureTests(unittest.TestCase):
    def test_reviewed_synthetic_archive_is_deterministic_and_matches_canonical_golden(self):
        with tempfile.TemporaryDirectory() as directory:
            first,second=Path(directory)/'first.dpk',Path(directory)/'second.zip'
            digest=B.build(first);self.assertEqual(digest,B.build(second));self.assertEqual(first.read_bytes(),second.read_bytes())
            self.assertEqual(digest,'584c217da05781b6c20e71683e893db1e9de4f907243f4c79f643a28623936d6')
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(set(archive.namelist()),set(B.FILES))
                self.assertTrue(all(item.compress_type==zipfile.ZIP_STORED and item.date_time==(1980,1,1,0,0,0) for item in archive.infolist()))
                manifest=ET.fromstring(archive.read('MANIFEST/manifest.xml'))
                self.assertEqual(manifest.tag,'MissionPackageManifest');self.assertEqual(manifest.get('version'),'2')
                config={item.get('name'):item.get('value') for item in manifest.find('Configuration')}
                self.assertEqual(config['uid'],'00000000-0000-4000-8000-000000000410')
                self.assertEqual(config['onReceiveImport'],'true');self.assertEqual(config['onReceiveDelete'],'false')
                entries={item.get('zipEntry') for item in manifest.find('Contents')}
                self.assertEqual(entries,set(archive.namelist())-{'MANIFEST/manifest.xml'})
                point=ET.fromstring(archive.read('cot/synthetic-android-mission-point.cot'))
                self.assertEqual(point.get('uid'),'synthetic-android-mission-point')
                self.assertEqual(point.find('detail/contact').get('callsign'),'SYNTHETIC-MISSION TEST')
                self.assertEqual((point.find('point').get('lat'),point.find('point').get('lon')),('0.0','0.0'))

    def test_builder_cannot_replace_existing_file_or_pack_tampered_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'existing.dpk';output.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):B.build(output)
            self.assertEqual(output.read_bytes(),b'existing')
            shutil.copytree(ROOT/'fixtures',root/'fixtures');shutil.copyfile(ROOT/'fixtures.lock.json',root/'fixtures.lock.json')
            (root/'fixtures/point.cot').write_bytes(b'changed')
            with patch.object(B,'ROOT',root),self.assertRaises(ValueError):B.build(root/'fresh.dpk')
            self.assertFalse((root/'fresh.dpk').exists())

    def test_qualifier_refuses_source_or_dependency_mismatch_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sources=root/'sources';sources.mkdir();maven=root/'maven';maven.mkdir()
            (sources/'Example.java').write_bytes(b'expected');(maven/'dependency.jar').write_bytes(b'expected')
            expected=hashlib.sha256(b'expected').hexdigest()
            lock={'takx':{'sources':{'Example.java':expected}},'dependencies':{'dependency.jar':{'bytes':8,'sha256':expected}}}
            (root/'inputs.lock.json').write_text(json.dumps(lock))
            with patch.object(Q,'ROOT',root),patch.object(Q.subprocess,'run') as command:
                (sources/'Example.java').write_bytes(b'wrong')
                with self.assertRaises(ValueError):Q.qualify(sources,maven,root,root/'first-output')
                command.assert_not_called();self.assertFalse((root/'first-output').exists())
                (sources/'Example.java').write_bytes(b'expected');(maven/'dependency.jar').write_bytes(b'mismatched')
                with self.assertRaises(ValueError):Q.qualify(sources,maven,root,root/'second-output')
                command.assert_not_called();self.assertFalse((root/'second-output').exists())

    def test_admission_profile_binds_four_actual_postimages_and_keeps_history(self):
        profile=P.profile()
        self.assertEqual(profile['profileId'],'takx57-mission-admission-v2')
        self.assertEqual(len(profile['sources']),4)
        self.assertEqual(sorted(item['scope'] for item in profile['sources'].values()),['Client','Platform','Platform','Platform'])
        historical=ROOT/'profiles/takx57-mission-admission-v1.json'
        self.assertEqual(P.sha(historical),'04678f0f0725c4695d41669783d1cf1332c5ccfd740cb3efa09f1db736d6a07a')
        old=json.loads(historical.read_text())
        self.assertEqual(P.sha(ROOT/old['patch']['file']),old['patch']['sha256'])
        self.assertFalse(profile['platformReceipt']['oldPlatformArtifactAllowed'])
        self.assertFalse(profile['extraction']['certificateAuthorizationSolved'])

    def test_projection_verification_rejects_extra_tampered_or_aliased_files(self):
        # Only tests the metadata/file verifier, never a compiler or API substitute.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'projection';out.mkdir();source=out/'source';source.mkdir()
            (source/'example.txt').write_bytes(b'unit metadata fixture')
            profile={'schema':1,'profileId':'unit-only','patch':{'sha256':'0'*64},'sourceRevision':'1'*40,
                     'sources':{'example.txt':{'preSha256':'2'*64,'postSha256':P.sha(source/'example.txt'),'scope':'unit'}}}
            (root/'admission-profile.json').write_text(json.dumps(profile))
            receipt={'schema':1,'profileId':'unit-only','profileSha256':P.sha(root/'admission-profile.json'),
                     'patchSha256':'0'*64,'sourceRevision':'1'*40,'projectorSha256':P.sha(P.__file__),
                     'sources':profile['sources'],'fullPlatformCompileAcceptance':False,'fullClientCompileAcceptance':False,'nativeTransferAcceptance':False}
            (out/'projection.json').write_text(json.dumps(receipt))
            with patch.object(P,'ROOT',root),patch.object(P,'profile',return_value=profile):
                P.verify(out)
                (source/'extra.txt').write_bytes(b'extra')
                with self.assertRaises(ValueError):P.verify(out)
                (source/'extra.txt').unlink();(source/'example.txt').write_bytes(b'changed')
                with self.assertRaises(ValueError):P.verify(out)
                (source/'example.txt').write_bytes(b'unit metadata fixture')
                receipt['fullPlatformCompileAcceptance']=True;(out/'projection.json').write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):P.verify(out)
                receipt['fullPlatformCompileAcceptance']=False;(out/'projection.json').write_text(json.dumps(receipt))
                external=root/'external';source.rename(external);source.symlink_to(external,target_is_directory=True)
                with self.assertRaises(ValueError):P.verify(out)

    def test_provenance_separates_synthetic_data_android_semantics_and_actual_takx_reader(self):
        lock=json.loads((ROOT/'inputs.lock.json').read_text())
        self.assertEqual(lock['referenceSemantics']['revision'],'9f6893dd657feacc35ec5de03dad721c2e44170e')
        self.assertEqual(lock['takx']['revision'],'0b59a9bb2d0e90dc35c9edfff1c2056daab2b713')
        self.assertEqual(len(lock['takx']['sources']),11)
        self.assertTrue(any(path.endswith('/PackageReader.java') for path in lock['takx']['sources']))
        self.assertEqual(len(lock['dependencies']),9)
        self.assertIn('original synthetic',json.loads((ROOT/'fixtures.lock.json').read_text())['kind'])


if __name__=='__main__':unittest.main()
